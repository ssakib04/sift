import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from livekit import rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, cli
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.llm_fallback import create_fallback_manager
from app.models.candidate import Candidate, CandidateParseResult, InterviewSession
from app.models.job import JobVersion
from app.services.interview_conductor import (
    Agenda,
    echoes_prompt,
    opening_line,
    plan_reply,
    spoken_sentences,
)
from app.services.interview_copilot import cv_profile_text
from app.services.interview_sessions import checklist_questions, close_interview_from_agent, save_spoken_line
from app.services.interview_transcript import transcript_notice
from app.services.local_speech import (
    BargeMeter,
    PiperSynthesizer,
    SpeechGate,
    WhisperRecognizer,
    ensure_piper_voice,
    float_to_pcm16,
    pcm16_to_float,
    is_audio_kind,
    resample_linear,
    split_pcm16,
)

logger = logging.getLogger(__name__)

server = AgentServer()
_engines: tuple[WhisperRecognizer, PiperSynthesizer] | None = None
_LISTEN_TIMEOUT = 90.0


@dataclass(frozen=True)
class Brief:
    candidate_name: str
    job_title: str
    company_name: str
    questions: tuple[str, ...]
    profile: str


def speech_engines() -> tuple[WhisperRecognizer, PiperSynthesizer]:
    """Load Whisper and Piper once per process. Both run on this machine."""
    global _engines
    if _engines is None:
        settings = get_settings()
        directory = Path(settings.speech_model_dir)
        voice = ensure_piper_voice(directory, settings.piper_voice)
        _engines = (
            WhisperRecognizer(settings.whisper_model, settings.whisper_device, str(directory)),
            PiperSynthesizer(voice),
        )
    return _engines


class CandidateEar:
    """Microphone audio from the candidate, plus a signal when they talk over the interviewer."""

    def __init__(self) -> None:
        self.frames: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.interrupt = asyncio.Event()
        self.speaking = False
        self._barge = BargeMeter()
        self._tasks: set[asyncio.Task[None]] = set()

    def watch(self, room: rtc.Room) -> None:
        room.on("track_subscribed", self._on_track)
        room.on("participant_disconnected", self._on_leave)
        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.track is not None:
                    self._on_track(publication.track, publication, participant)

    def _on_leave(self, participant: rtc.RemoteParticipant) -> None:
        if participant.identity == "candidate":
            self.frames.put_nowait(None)

    def _on_track(self, track: rtc.Track, _publication: rtc.TrackPublication, participant: rtc.RemoteParticipant) -> None:
        if participant.identity != "candidate" or not _is_audio(track):
            return
        logger.info("interviewer_listening identity=%s", participant.identity)
        task = asyncio.create_task(self._pump(track))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _pump(self, track: rtc.Track) -> None:
        try:
            stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
            async for event in stream:
                frame = getattr(event, "frame", event)
                pcm = _frame_pcm(frame)
                if not pcm:
                    continue
                if self.speaking and self._barge.push(pcm):
                    self.interrupt.set()
                    self.speaking = False
                elif not self.speaking:
                    self._barge.reset()
                self.frames.put_nowait(pcm)
        except Exception:
            logger.exception("interviewer_listen_failed")

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


async def load_brief(session_id: str) -> Brief | None:
    try:
        interview_id = uuid.UUID(session_id)
    except ValueError:
        return None
    from app.core.database import SessionFactory

    settings = get_settings()
    async with SessionFactory() as db:
        row = await db.scalar(
            select(InterviewSession)
            .where(InterviewSession.id == interview_id)
            .options(
                selectinload(InterviewSession.candidate)
                .selectinload(Candidate.version)
                .selectinload(JobVersion.job)
            )
        )
        if row is None or row.candidate is None or row.candidate.version is None or row.candidate.version.job is None:
            return None
        questions = await checklist_questions(db, row.job_version_id)
        parse = await db.scalar(
            select(CandidateParseResult).where(CandidateParseResult.candidate_id == row.candidate.id)
        )
        raw = parse.raw_text if parse is not None and parse.status == "parsed" else ""
        return Brief(
            candidate_name=row.candidate.full_name,
            job_title=row.candidate.version.job.title,
            company_name=settings.company_name,
            questions=tuple(questions),
            profile=cv_profile_text(row.candidate.full_name, raw),
        )


async def conduct(ctx: JobContext) -> None:
    brief = await load_brief(ctx.room.name)
    if brief is None:
        logger.warning("interviewer_brief_missing room=%s", ctx.room.name)
        return
    ear = CandidateEar()
    ear.watch(ctx.room)
    if not await _wait_for_candidate(ctx.room):
        return
    await _publish(ctx, {"type": "avatar"}, topic="interview", identities=["candidate"])
    recognizer, synthesizer = await asyncio.to_thread(speech_engines)
    hello = opening_line(brief.company_name, brief.job_title, brief.candidate_name)
    source: rtc.AudioSource | None = None
    agenda = Agenda(questions=brief.questions)
    lines = [f"recruiter: {hello}"]
    quiet = 0
    planner = create_fallback_manager()
    try:
        source = await _speak(ctx, ear, synthesizer, hello, source)
        await _record(ctx, "recruiter", hello)
        first, agenda = await plan_reply(
            planner,
            agenda,
            company=brief.company_name,
            job_title=brief.job_title,
            profile=brief.profile,
            transcript="\n".join(lines),
            heard="",
        )
        lines.append(f"recruiter: {first.say}")
        source = await _speak(ctx, ear, synthesizer, first.say, source)
        await _record(ctx, "recruiter", first.say)
        while True:
            heard = await _listen(ear, recognizer, lines[-1].removeprefix("recruiter: "))
            if heard is None:
                await close_interview_from_agent(ctx.room.name)
                break
            if not heard:
                quiet += 1
                if quiet >= 3:
                    farewell = "I am going to stop here and open the skill quiz. Thank you for your time."
                    source = await _speak(ctx, ear, synthesizer, farewell, source)
                    await _record(ctx, "recruiter", farewell)
                    await _publish(ctx, {"type": "quiz"}, topic="interview", identities=["candidate"])
                    await asyncio.sleep(2)
                    await close_interview_from_agent(ctx.room.name)
                    break
                nudge = "I did not catch that. Please go ahead when you are ready."
                source = await _speak(ctx, ear, synthesizer, nudge, source)
                await _record(ctx, "recruiter", nudge)
                lines.append(f"recruiter: {nudge}")
                continue
            quiet = 0
            lines.append(f"candidate: {heard}")
            await _record(ctx, "candidate", heard)
            planned = time.perf_counter()
            utterance, agenda = await plan_reply(
                planner,
                agenda,
                company=brief.company_name,
                job_title=brief.job_title,
                profile=brief.profile,
                transcript="\n".join(lines),
                heard=heard,
            )
            logger.info("interviewer_planned seconds=%.1f", time.perf_counter() - planned)
            lines.append(f"recruiter: {utterance.say}")
            source = await _speak(ctx, ear, synthesizer, utterance.say, source)
            await _record(ctx, "recruiter", utterance.say)
            if utterance.offer_quiz:
                await _publish(ctx, {"type": "quiz"}, topic="interview", identities=["candidate"])
            if utterance.finished:
                await asyncio.sleep(2)
                await close_interview_from_agent(ctx.room.name)
                break
    finally:
        await ear.close()


async def _listen(ear: CandidateEar, recognizer: WhisperRecognizer, last_spoken: str) -> str | None:
    gate = SpeechGate()
    try:
        while True:
            pcm = await asyncio.wait_for(ear.frames.get(), timeout=_LISTEN_TIMEOUT)
            if pcm is None:
                return None
            heard = gate.push(pcm)
            if heard is None:
                continue
            started = time.perf_counter()
            text = await asyncio.to_thread(recognizer.transcribe, heard, 16000)
            cleaned = " ".join(text.split())
            logger.info(
                "interviewer_transcribed seconds=%.1f chars=%s",
                time.perf_counter() - started,
                len(cleaned),
            )
            if cleaned and not echoes_prompt(cleaned, last_spoken):
                return cleaned
    except TimeoutError:
        return ""


_PLAYBACK_RATE = 48000


def _playback_pcm(audio: bytes, rate: int) -> bytes:
    if not audio or rate == _PLAYBACK_RATE:
        return audio
    return float_to_pcm16(resample_linear(pcm16_to_float(audio), rate, _PLAYBACK_RATE))


async def _speak(
    ctx: JobContext,
    ear: CandidateEar,
    synthesizer: PiperSynthesizer,
    text: str,
    source: rtc.AudioSource | None,
) -> rtc.AudioSource:
    for sentence in spoken_sentences(text):
        audio, rate = await asyncio.to_thread(synthesizer.synthesize, sentence)
        audio = _playback_pcm(audio, rate)
        if source is None:
            source = rtc.AudioSource(_PLAYBACK_RATE, 1)
            track = rtc.LocalAudioTrack.create_audio_track("interviewer", source)
            publication = await ctx.room.local_participant.publish_track(
                track,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )
            logger.info("interviewer_audio_published sid=%s", getattr(publication, "sid", ""))
            await _name_interviewer(ctx)
        ear.interrupt.clear()
        ear.speaking = True
        try:
            for frame in split_pcm16(audio, max(1, _PLAYBACK_RATE // 50)):
                if ear.interrupt.is_set():
                    source.clear_queue()
                    break
                await source.capture_frame(rtc.AudioFrame(frame, _PLAYBACK_RATE, 1, len(frame) // 2))
            if not ear.interrupt.is_set():
                await source.wait_for_playout()
        finally:
            ear.speaking = False
        if ear.interrupt.is_set():
            break
    if source is None:
        source = rtc.AudioSource(_PLAYBACK_RATE, 1)
    return source


async def _record(ctx: JobContext, speaker: str, text: str) -> None:
    notice = transcript_notice(speaker, text, final=True)
    if not notice["text"]:
        return
    try:
        await save_spoken_line(ctx.room.name, speaker, str(notice["text"]), final=True)
    except Exception:
        logger.exception("interviewer_transcript_failed")


async def _publish(ctx: JobContext, payload: dict[str, object], *, topic: str, identities: list[str]) -> None:
    try:
        await ctx.room.local_participant.publish_data(
            json.dumps(payload).encode(),
            reliable=True,
            destination_identities=identities,
            topic=topic,
        )
    except Exception:
        logger.exception("interviewer_publish_failed")


async def _wait_for_candidate(room: rtc.Room) -> bool:
    if any(participant.identity == "candidate" for participant in room.remote_participants.values()):
        return True
    arrived = asyncio.Event()

    def on_join(participant: rtc.RemoteParticipant) -> None:
        if participant.identity == "candidate":
            arrived.set()

    room.on("participant_connected", on_join)
    try:
        await asyncio.wait_for(arrived.wait(), timeout=180)
    except TimeoutError:
        logger.warning("interviewer_candidate_missing")
        return False
    finally:
        room.off("participant_connected", on_join)
    return True


async def _name_interviewer(ctx: JobContext) -> None:
    rename = getattr(ctx.room.local_participant, "set_name", None)
    if rename is None:
        return
    try:
        await rename("Interviewer")
    except Exception:
        logger.exception("interviewer_name_failed")


def _is_audio(track: rtc.Track) -> bool:
    return is_audio_kind(getattr(track, "kind", None))


def _frame_pcm(frame: object) -> bytes:
    data = bytes(getattr(frame, "data", b""))
    rate = getattr(frame, "sample_rate", 16000)
    if not isinstance(rate, int) or rate <= 0 or rate == 16000:
        return data
    return float_to_pcm16(resample_linear(pcm16_to_float(data), rate, 16000))


@server.rtc_session(agent_name="sift-interviewer")
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await conduct(ctx)


if __name__ == "__main__":
    cli.run_app(server)
