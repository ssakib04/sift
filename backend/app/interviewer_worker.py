import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from livekit import rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, JobProcess, cli
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.llm_fallback import FallbackLLMManager, create_fallback_manager
from app.models.candidate import Candidate, CandidateParseResult, InterviewSession
from app.models.job import JobVersion
from app.services.interview_conductor import (
    ANSWER_FILLERS,
    QUESTION_FILLERS,
    QUIZ_LINE,
    SORRY_LINE,
    Agenda,
    Utterance,
    candidate_asked,
    closing_reply,
    echoes_prompt,
    ends_turn_early,
    filler_line,
    interruption_is_noise,
    keyword_turn_kind,
    opening_line,
    plan_reply,
    silence_nudge,
    spoken_sentences,
)
from app.services.interview_copilot import cv_profile_text
from app.services.interview_sessions import checklist_questions, close_interview_from_agent, save_spoken_line
from app.services.interview_transcript import transcript_notice
from app.services.local_speech import (
    BargeMeter,
    KokoroSynthesizer,
    PiperSynthesizer,
    SpeechGate,
    SpeechSynthesizer,
    ensure_kokoro_files,
    speech_prompt,
    WhisperRecognizer,
    ensure_piper_voice,
    float_to_pcm16,
    pcm16_to_float,
    is_audio_kind,
    is_video_kind,
    resample_linear,
    split_pcm16,
)

logger = logging.getLogger(__name__)

_engines: tuple[WhisperRecognizer, SpeechSynthesizer] | None = None
_LISTEN_TIMEOUT = 90.0
_QUIET_LIMIT = 12.0
_INTERRUPT_WAIT = 5.0
_INTERRUPT_SILENCE_MS = 2400
_INTERRUPT_SHORT_SILENCE_MS = 1600
_EARLY_AFTER_MS = 900
_EARLY_LONGEST_MS = 6000
_FILLER_AFTER = 0.9
_TURN_FAILURES = 3


@dataclass(frozen=True)
class Brief:
    candidate_name: str
    job_title: str
    company_name: str
    questions: tuple[str, ...]
    profile: str


def speech_engines() -> tuple[WhisperRecognizer, SpeechSynthesizer]:
    """Load Whisper and the voice once per process. Both run on this machine."""
    global _engines
    if _engines is None:
        settings = get_settings()
        directory = Path(settings.speech_model_dir)
        _engines = (
            WhisperRecognizer(settings.whisper_model, settings.whisper_device, str(directory)),
            _voice(directory, settings.speech_voice_engine, settings.kokoro_voice, settings.piper_voice),
        )
    return _engines


def _voice(directory: Path, engine: str, kokoro_voice: str, piper_voice: str) -> SpeechSynthesizer:
    """Kokoro sounds closer to a person. Piper is kept for when Kokoro cannot load."""
    if engine == "kokoro":
        try:
            model, voices = ensure_kokoro_files(directory)
            synthesizer = KokoroSynthesizer(model, voices, kokoro_voice)
            logger.info("interviewer_voice engine=kokoro voice=%s", kokoro_voice)
            return synthesizer
        except Exception:
            logger.exception("interviewer_kokoro_failed")
    logger.info("interviewer_voice engine=piper voice=%s", piper_voice)
    return PiperSynthesizer(ensure_piper_voice(directory, piper_voice))


def prewarm(_process: JobProcess) -> None:
    """Load the speech models before a call arrives, so the first words are not delayed."""
    try:
        speech_engines()
    except Exception:
        logger.exception("interviewer_prewarm_failed")


server = AgentServer(setup_fnc=prewarm, num_idle_processes=1, initialize_process_timeout=180.0)


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
    await _publish(ctx, {"type": "avatar", "state": "thinking"}, topic="interview", identities=["candidate"])
    recognizer, synthesizer = await asyncio.to_thread(speech_engines)
    recognizer.prompt = speech_prompt(list(brief.questions), brief.profile)
    hello = opening_line(brief.company_name, brief.job_title, brief.candidate_name)
    agenda = Agenda(questions=brief.questions)
    lines = [f"recruiter: {hello}"]
    quiet = 0
    pending = ""
    planner = create_fallback_manager()
    clips: dict[str, bytes] = {}
    slot: dict[str, rtc.AudioSource | None] = {"source": None}
    warming = asyncio.create_task(_warm_clips(synthesizer, clips, (*ANSWER_FILLERS, *QUESTION_FILLERS, SORRY_LINE)))
    turns = 0
    failures = 0

    try:
        greeting = await _deliver(ctx, ear, recognizer, synthesizer, hello, slot["source"], clips)
        slot["source"] = greeting.source
        if greeting.heard is None:
            await close_interview_from_agent(ctx.room.name)
            return
        pending = greeting.heard

        while True:
            if pending:
                heard = pending
                pending = ""
            else:
                heard = await _attend(ctx, ear, recognizer, lines[-1].removeprefix("recruiter: "))
            if heard is None:
                await close_interview_from_agent(ctx.room.name)
                break
            if not heard:
                quiet += 1
                await _mind(ctx, "waiting")
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
            await _mind(ctx, "thinking")
            kind = keyword_turn_kind(heard)
            planned = time.perf_counter()
            try:
                plan_task = asyncio.create_task(
                    plan_reply(
                        planner,
                        agenda,
                        company=brief.company_name,
                        job_title=brief.job_title,
                        profile=brief.profile,
                        transcript="\n".join(lines),
                        heard=heard,
                        turn_kind=kind,
                        camera_on=_candidate_camera(ctx.room),
                    )
                )
                await _record(ctx, "candidate", heard)
                await _fill_gap(ctx, ear, plan_task, filler_line(kind, turns), slot, clips)
                utterance, agenda = await plan_task
                failures = 0
            except Exception:
                logger.exception("interviewer_turn_failed")
                failures += 1
                if failures >= _TURN_FAILURES:
                    await close_interview_from_agent(ctx.room.name)
                    break
                utterance = Utterance(say=SORRY_LINE, covered=(), finished=False, offer_quiz=False)
            turns += 1
            logger.info("interviewer_planned kind=%s seconds=%.1f", kind, time.perf_counter() - planned)
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
                await _finish(ctx, ear, recognizer, synthesizer, planner, brief, slot, clips, lines)
                break
    finally:
        warming.cancel()
        await ear.close()


async def _warm_clips(synthesizer: SpeechSynthesizer, clips: dict[str, bytes], texts: tuple[str, ...]) -> None:
    """Synthesize the short fillers once, so they can play the moment a turn ends."""
    for text in texts:
        try:
            clips[text] = await _sentence_audio(synthesizer, text, clips)
        except Exception:
            logger.exception("interviewer_clip_failed")


async def _fill_gap(
    ctx: JobContext,
    ear: CandidateEar,
    task: "asyncio.Task[tuple[Utterance, Agenda]]",
    filler: str,
    slot: dict[str, rtc.AudioSource | None],
    clips: dict[str, bytes],
) -> None:
    """Say a short acknowledgement when the reply is not ready quickly, so the line never goes dead."""
    done, _pending = await asyncio.wait({task}, timeout=_FILLER_AFTER)
    if done:
        return
    audio = clips.get(filler)
    if not audio:
        return
    source = await _ensure_source(ctx, slot["source"])
    slot["source"] = source
    await _play_audio(ear, source, audio)


def _candidate_camera(room: rtc.Room) -> bool | None:
    """Whether the candidate's camera is published and not muted. None when they are not in the room."""
    for participant in room.remote_participants.values():
        if participant.identity != "candidate":
            continue
        cameras = [
            publication
            for publication in participant.track_publications.values()
            if is_video_kind(getattr(publication, "kind", None))
        ]
        return any(not getattr(publication, "muted", False) for publication in cameras)
    return None


async def _finish(
    ctx: JobContext,
    ear: CandidateEar,
    recognizer: WhisperRecognizer,
    synthesizer: SpeechSynthesizer,
    planner: FallbackLLMManager,
    brief: Brief,
    slot: dict[str, rtc.AudioSource | None],
    clips: dict[str, bytes],
    lines: list[str],
) -> None:
    heard = await _attend(ctx, ear, recognizer, lines[-1].removeprefix("recruiter: "))
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
    silence_ms: int = 4800,
    short_silence_ms: int | None = 3200,
) -> str | None:
    def fresh_gate() -> SpeechGate:
        return SpeechGate(silence_ms=silence_ms, short_silence_ms=short_silence_ms)

    gate = fresh_gate()
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
            early = gate.early_audio(_EARLY_AFTER_MS, _EARLY_LONGEST_MS)
            if early is not None:
                text = await _transcribe(recognizer, early)
                if text and ends_turn_early(text) and not echoes_prompt(text, last_spoken):
                    logger.info("interviewer_turn_ended_early chars=%s", len(text))
                    return text
            if on_hold is not None and gate.wants_hold():
                await on_hold()
            if not gate.armed and time.perf_counter() - started >= idle_seconds:
                return ""
            continue
        cleaned = await _transcribe(recognizer, audio)
        if cleaned and not echoes_prompt(cleaned, last_spoken):
            return cleaned
        gate = fresh_gate()
        started = time.perf_counter()


async def _transcribe(recognizer: WhisperRecognizer, audio: bytes) -> str:
    transcribed = time.perf_counter()
    text = await asyncio.to_thread(recognizer.transcribe, audio, 16000)
    cleaned = " ".join(text.split())
    logger.info(
        "interviewer_transcribed seconds=%.1f chars=%s",
        time.perf_counter() - transcribed,
        len(cleaned),
    )
    return cleaned


_PLAYBACK_RATE = 48000


def _playback_pcm(audio: bytes, rate: int) -> bytes:
    if not audio or rate == _PLAYBACK_RATE:
        return audio
    return float_to_pcm16(resample_linear(pcm16_to_float(audio), rate, _PLAYBACK_RATE))


async def _deliver(
    ctx: JobContext,
    ear: CandidateEar,
    recognizer: WhisperRecognizer,
    synthesizer: SpeechSynthesizer,
    text: str,
    source: rtc.AudioSource | None,
    clips: dict[str, bytes],
) -> Delivery:
    playback = await _speak(ctx, ear, synthesizer, text, source, clips)
    if not playback.interrupted:
        await _record(ctx, "recruiter", text)
        return Delivery(playback.source, "", text)
    heard = await _attend(
        ctx,
        ear,
        recognizer,
        playback.spoken or text,
        idle_seconds=_INTERRUPT_WAIT,
        silence_ms=_INTERRUPT_SILENCE_MS,
        short_silence_ms=_INTERRUPT_SHORT_SILENCE_MS,
    )
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
        heard_again = await _attend(
            ctx,
            ear,
            recognizer,
            rest.spoken or playback.remaining,
            idle_seconds=_INTERRUPT_WAIT,
            silence_ms=_INTERRUPT_SILENCE_MS,
            short_silence_ms=_INTERRUPT_SHORT_SILENCE_MS,
        )
        spoken = " ".join(part for part in (playback.spoken, rest.spoken) if part)
        await _record(ctx, "recruiter", spoken)
        return Delivery(rest.source, heard_again, spoken)
    await _record(ctx, "recruiter", text)
    return Delivery(rest.source, "", text)


async def _speak(
    ctx: JobContext,
    ear: CandidateEar,
    synthesizer: SpeechSynthesizer,
    text: str,
    source: rtc.AudioSource | None,
    clips: dict[str, bytes],
) -> Playback:
    await _mind(ctx, "speaking")
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


async def _sentence_audio(synthesizer: SpeechSynthesizer, sentence: str, clips: dict[str, bytes]) -> bytes:
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


async def _mind(ctx: JobContext, state: str) -> None:
    await _publish(ctx, {"type": "avatar", "state": state}, topic="interview", identities=["candidate"])


async def _attend(
    ctx: JobContext,
    ear: CandidateEar,
    recognizer: WhisperRecognizer,
    last_spoken: str,
    *,
    on_hold: Callable[[], Awaitable[None]] | None = None,
    idle_seconds: float = _QUIET_LIMIT,
    silence_ms: int = 4800,
    short_silence_ms: int | None = 3200,
) -> str | None:
    await _mind(ctx, "listening")
    return await _listen(
        ear,
        recognizer,
        last_spoken,
        on_hold=on_hold,
        idle_seconds=idle_seconds,
        silence_ms=silence_ms,
        short_silence_ms=short_silence_ms,
    )


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
