import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from livekit import rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, cli
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.llm_fallback import FallbackLLMManager, create_fallback_manager
from app.models.candidate import Candidate, CandidateParseResult, InterviewSession
from app.models.job import JobVersion
from app.services.interview_conductor import (
    HOLD_LINE,
    QUIZ_LINE,
    Agenda,
    acknowledgement,
    candidate_asked,
    closing_reply,
    echoes_prompt,
    interruption_is_noise,
    opening_line,
    plan_reply,
    should_acknowledge,
    silence_nudge,
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
_QUIET_LIMIT = 12.0
_INTERRUPT_WAIT = 1.5


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
        self.capture = True
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
                    self.capture = True
                elif not self.speaking:
                    self._barge.reset()
                if not self.capture:
                    continue
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


@dataclass
class Playback:
    source: rtc.AudioSource
    interrupted: bool
    spoken: str
    remaining: str


@dataclass
class Delivery:
    source: rtc.AudioSource
    heard: str | None
    spoken: str


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
    agenda = Agenda(questions=brief.questions)
    lines = [f"recruiter: {hello}"]
    quiet = 0
    ack_index = 0
    pending = ""
    planner = create_fallback_manager()
    clips: dict[str, bytes] = {}
    slot: dict[str, rtc.AudioSource | None] = {"source": None}

    async def hold() -> None:
        ear.capture = False
        try:
            slot["source"] = await _play_clip(ctx, ear, slot["source"], clips[HOLD_LINE])
        finally:
            ear.capture = True
            ear.interrupt.clear()

    try:
        greeting = await _deliver(ctx, ear, recognizer, synthesizer, hello, slot["source"], clips)
        slot["source"] = greeting.source
        if greeting.heard is None:
            await close_interview_from_agent(ctx.room.name)
            return
        pending = greeting.heard
        warm_task = asyncio.create_task(_warm_clips(synthesizer))

        async def ready_clips() -> dict[str, bytes]:
            return await warm_task

        while True:
            clips = await ready_clips()
            if pending:
                heard = pending
                pending = ""
            else:
                heard = await _listen(ear, recognizer, lines[-1].removeprefix("recruiter: "), on_hold=hold)
            if heard is None:
                await close_interview_from_agent(ctx.room.name)
                break
            if not heard:
                quiet += 1
                if quiet >= 3:
                    farewell = await _deliver(
                        ctx,
                        ear,
                        recognizer,
                        synthesizer,
                        "I am going to stop here. Thank you for your time.",
                        slot["source"],
                        clips,
                    )
                    slot["source"] = farewell.source
                    await _publish(ctx, {"type": "quiz"}, topic="interview", identities=["candidate"])
                    await asyncio.sleep(2)
                    await close_interview_from_agent(ctx.room.name)
                    break
                nudge = silence_nudge(quiet)
                spoken = await _deliver(ctx, ear, recognizer, synthesizer, nudge, slot["source"], clips)
                slot["source"] = spoken.source
                lines.append(f"recruiter: {nudge}")
                if spoken.heard is None:
                    await close_interview_from_agent(ctx.room.name)
                    break
                if spoken.heard:
                    pending = spoken.heard
                continue
            quiet = 0
            lines.append(f"candidate: {heard}")
            await _record(ctx, "candidate", heard)
            if should_acknowledge(heard):
                plan_task = asyncio.create_task(
                    plan_reply(
                        planner,
                        agenda,
                        company=brief.company_name,
                        job_title=brief.job_title,
                        profile=brief.profile,
                        transcript="\n".join(lines),
                        heard=heard,
                    )
                )
                reacted = await _deliver(
                    ctx,
                    ear,
                    recognizer,
                    synthesizer,
                    acknowledgement(ack_index),
                    slot["source"],
                    clips,
                )
                ack_index += 1
                slot["source"] = reacted.source
                lines.append(f"recruiter: {acknowledgement(ack_index - 1)}")
                if reacted.heard is None:
                    await _drop(plan_task)
                    await close_interview_from_agent(ctx.room.name)
                    break
                if reacted.heard:
                    await _drop(plan_task)
                    pending = reacted.heard
                    continue
                planned = time.perf_counter()
                utterance, agenda = await plan_task
                logger.info("interviewer_planned seconds=%.1f", time.perf_counter() - planned)
            else:
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
            reply = await _deliver(ctx, ear, recognizer, synthesizer, utterance.say, slot["source"], clips)
            slot["source"] = reply.source
            if reply.heard is None:
                await close_interview_from_agent(ctx.room.name)
                break
            if reply.heard:
                pending = reply.heard
                continue
            if utterance.finished:
                await _finish(ctx, ear, recognizer, synthesizer, planner, brief, slot, clips, lines, hold)
                break
    finally:
        await ear.close()


async def _drop(task: asyncio.Task[tuple[object, Agenda]]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _finish(
    ctx: JobContext,
    ear: CandidateEar,
    recognizer: WhisperRecognizer,
    synthesizer: PiperSynthesizer,
    planner: FallbackLLMManager,
    brief: Brief,
    slot: dict[str, rtc.AudioSource | None],
    clips: dict[str, bytes],
    lines: list[str],
    hold: Callable[[], Awaitable[None]],
) -> None:
    heard = await _listen(ear, recognizer, lines[-1].removeprefix("recruiter: "), on_hold=hold)
    if heard is None:
        await close_interview_from_agent(ctx.room.name)
        return
    if heard:
        lines.append(f"candidate: {heard}")
        await _record(ctx, "candidate", heard)
        if candidate_asked(heard):
            reply = await closing_reply(
                planner,
                company=brief.company_name,
                job_title=brief.job_title,
                heard=heard,
            )
            if reply:
                spoken = await _deliver(ctx, ear, recognizer, synthesizer, reply, slot["source"], clips)
                slot["source"] = spoken.source
                if spoken.heard is None:
                    await close_interview_from_agent(ctx.room.name)
                    return
    quiz = await _deliver(ctx, ear, recognizer, synthesizer, QUIZ_LINE, slot["source"], clips)
    slot["source"] = quiz.source
    await _publish(ctx, {"type": "quiz"}, topic="interview", identities=["candidate"])
    await asyncio.sleep(2)
    await close_interview_from_agent(ctx.room.name)


async def _listen(
    ear: CandidateEar,
    recognizer: WhisperRecognizer,
    last_spoken: str,
    *,
    on_hold: Callable[[], Awaitable[None]] | None = None,
    idle_seconds: float = _QUIET_LIMIT,
) -> str | None:
    gate = SpeechGate()
    started = time.perf_counter()
    while True:
        try:
            pcm = await asyncio.wait_for(ear.frames.get(), timeout=1.0)
        except TimeoutError:
            if not gate.armed and time.perf_counter() - started >= idle_seconds:
                return ""
            if time.perf_counter() - started >= _LISTEN_TIMEOUT:
                return ""
            continue
        if pcm is None:
            return None
        audio = gate.push(pcm)
        if audio is None:
            if on_hold is not None and gate.wants_hold():
                await on_hold()
            if not gate.armed and time.perf_counter() - started >= idle_seconds:
                return ""
            continue
        transcribed = time.perf_counter()
        text = await asyncio.to_thread(recognizer.transcribe, audio, 16000)
        cleaned = " ".join(text.split())
        logger.info(
            "interviewer_transcribed seconds=%.1f chars=%s",
            time.perf_counter() - transcribed,
            len(cleaned),
        )
        if cleaned and not echoes_prompt(cleaned, last_spoken):
            return cleaned
        gate = SpeechGate()
        started = time.perf_counter()


_PLAYBACK_RATE = 48000


def _playback_pcm(audio: bytes, rate: int) -> bytes:
    if not audio or rate == _PLAYBACK_RATE:
        return audio
    return float_to_pcm16(resample_linear(pcm16_to_float(audio), rate, _PLAYBACK_RATE))


async def _warm_clips(synthesizer: PiperSynthesizer) -> dict[str, bytes]:
    clips: dict[str, bytes] = {}
    for line in (acknowledgement(0), acknowledgement(1), acknowledgement(2), HOLD_LINE):
        audio, rate = await asyncio.to_thread(synthesizer.synthesize, line)
        clips[line] = _playback_pcm(audio, rate)
    return clips


async def _deliver(
    ctx: JobContext,
    ear: CandidateEar,
    recognizer: WhisperRecognizer,
    synthesizer: PiperSynthesizer,
    text: str,
    source: rtc.AudioSource | None,
    clips: dict[str, bytes],
) -> Delivery:
    playback = await _speak(ctx, ear, synthesizer, text, source, clips)
    if not playback.interrupted:
        await _record(ctx, "recruiter", text)
        return Delivery(playback.source, "", text)
    heard = await _listen(ear, recognizer, playback.spoken or text, idle_seconds=_INTERRUPT_WAIT)
    if heard is None:
        await _record(ctx, "recruiter", playback.spoken)
        return Delivery(playback.source, None, playback.spoken)
    if not interruption_is_noise(heard, text):
        await _record(ctx, "recruiter", playback.spoken)
        return Delivery(playback.source, heard, playback.spoken)
    if not playback.remaining:
        await _record(ctx, "recruiter", text)
        return Delivery(playback.source, "", text)
    rest = await _speak(ctx, ear, synthesizer, playback.remaining, playback.source, clips)
    if rest.interrupted:
        heard_again = await _listen(ear, recognizer, rest.spoken or playback.remaining, idle_seconds=_INTERRUPT_WAIT)
        spoken = " ".join(part for part in (playback.spoken, rest.spoken) if part)
        await _record(ctx, "recruiter", spoken)
        return Delivery(rest.source, heard_again, spoken)
    await _record(ctx, "recruiter", text)
    return Delivery(rest.source, "", text)


async def _speak(
    ctx: JobContext,
    ear: CandidateEar,
    synthesizer: PiperSynthesizer,
    text: str,
    source: rtc.AudioSource | None,
    clips: dict[str, bytes],
) -> Playback:
    sentences = list(spoken_sentences(text))
    source = await _ensure_source(ctx, source)
    if not sentences:
        return Playback(source, False, "", "")
    pending: asyncio.Task[bytes] | None = asyncio.create_task(_sentence_audio(synthesizer, sentences[0], clips))
    spoken: list[str] = []
    try:
        for index, sentence in enumerate(sentences):
            audio = await pending if pending is not None else b""
            pending = None
            if index + 1 < len(sentences):
                pending = asyncio.create_task(_sentence_audio(synthesizer, sentences[index + 1], clips))
            if await _play_audio(ear, source, audio):
                if pending is not None:
                    pending.cancel()
                return Playback(source, True, " ".join(spoken), " ".join(sentences[index:]))
            spoken.append(sentence)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
    return Playback(source, False, text, "")


async def _sentence_audio(synthesizer: PiperSynthesizer, sentence: str, clips: dict[str, bytes]) -> bytes:
    cached = clips.get(sentence)
    if cached is not None:
        return cached
    audio, rate = await asyncio.to_thread(synthesizer.synthesize, sentence)
    return _playback_pcm(audio, rate)


async def _play_clip(
    ctx: JobContext,
    ear: CandidateEar,
    source: rtc.AudioSource | None,
    audio: bytes,
) -> rtc.AudioSource:
    source = await _ensure_source(ctx, source)
    await _play_audio(ear, source, audio)
    return source


async def _ensure_source(ctx: JobContext, source: rtc.AudioSource | None) -> rtc.AudioSource:
    if source is not None:
        return source
    source = rtc.AudioSource(_PLAYBACK_RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("interviewer", source)
    publication = await ctx.room.local_participant.publish_track(
        track,
        rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
    )
    logger.info("interviewer_audio_published sid=%s", getattr(publication, "sid", ""))
    await _name_interviewer(ctx)
    return source


async def _play_audio(ear: CandidateEar, source: rtc.AudioSource, audio: bytes) -> bool:
    """Play PCM. Return True when the candidate talks over the line."""
    if not audio:
        return False
    ear.interrupt.clear()
    ear.speaking = True
    try:
        for frame in split_pcm16(audio, max(1, _PLAYBACK_RATE // 50)):
            if ear.interrupt.is_set():
                source.clear_queue()
                return True
            await source.capture_frame(rtc.AudioFrame(frame, _PLAYBACK_RATE, 1, len(frame) // 2))
        if ear.interrupt.is_set():
            source.clear_queue()
            return True
        await source.wait_for_playout()
    finally:
        ear.speaking = False
    return ear.interrupt.is_set()


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
