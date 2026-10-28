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
from app.core.logging import configure_logging
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
from app.services.question_bank import list_question_texts, spoken_with_bank
from app.services.interview_sessions import checklist_questions, close_interview_from_agent, save_spoken_line
from app.services.cloud_speech import GroqRecognizer, GroqSynthesizer
from app.services.interview_transcript import transcript_notice
from app.services.local_speech import (
    BargeMeter,
    KokoroSynthesizer,
    PiperSynthesizer,
    SpeechGate,
    SpeechSynthesizer,
    continued_in_silence,
    ensure_kokoro_files,
    prepare_speech_runtime,
    resolve_whisper_device,
    speech_prompt,
    WhisperRecognizer,
    ensure_piper_voice,
    float_to_pcm16,
    pcm16_rms,
    pcm16_to_float,
    is_audio_kind,
    is_video_kind,
    resample_linear,
    split_pcm16,
)

logger = logging.getLogger(__name__)

_engines: tuple[WhisperRecognizer | GroqRecognizer, SpeechSynthesizer] | None = None
_LISTEN_TIMEOUT = 90.0
_QUIET_LIMIT = 12.0
_INTERRUPT_WAIT = 5.0
_ANSWER_SILENCE_MS = 4000
_SHORT_SILENCE_MS = 4000
_INTERRUPT_SILENCE_MS = 4000
_INTERRUPT_SHORT_SILENCE_MS = 4000
_EARLY_AFTER_MS = 4000
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
    bank: tuple[str, ...] = ()


def speech_engines() -> tuple[WhisperRecognizer | GroqRecognizer, SpeechSynthesizer]:
    """Load hearing and speech once per process. Groq is used when its key is set."""
    global _engines
    if _engines is None:
        settings = get_settings()
        if settings.groq_api_key.strip():
            logger.info(
                "interviewer_speech engine=groq stt=%s voice=%s",
                settings.groq_stt_model,
                settings.groq_tts_voice,
            )
            _engines = (
                GroqRecognizer(settings.groq_api_key.strip(), settings.groq_stt_model),
                GroqSynthesizer(
                    settings.groq_api_key.strip(),
                    settings.groq_tts_model,
                    settings.groq_tts_voice,
                ),
            )
            return _engines
        directory = Path(settings.speech_model_dir)
        prepare_speech_runtime(settings.whisper_cpu_threads)
        device = resolve_whisper_device(settings.whisper_device)
        logger.info(
            "interviewer_whisper model=%s device=%s cpu_threads=%s",
            settings.whisper_model,
            device,
            settings.whisper_cpu_threads,
        )
        _engines = (
            WhisperRecognizer(settings.whisper_model, device, str(directory), settings.whisper_cpu_threads),
            _voice(
                directory,
                settings.speech_voice_engine,
                settings.kokoro_voice,
                settings.piper_voice,
                settings.kokoro_speed,
            ),
        )
    return _engines


def _voice(
    directory: Path,
    engine: str,
    kokoro_voice: str,
    piper_voice: str,
    kokoro_speed: float = 1.08,
) -> SpeechSynthesizer:
    """Kokoro sounds closer to a person. Piper is kept for when Kokoro cannot load."""
    if engine == "kokoro":
        try:
            model, voices = ensure_kokoro_files(directory)
            synthesizer = KokoroSynthesizer(
                model,
                voices,
                kokoro_voice,
                speed=kokoro_speed,
                cpu_threads=get_settings().whisper_cpu_threads,
            )
            logger.info(
                "interviewer_voice engine=kokoro voice=%s speed=%.2f provider=%s",
                kokoro_voice,
                kokoro_speed,
                getattr(synthesizer, "provider", "CPUExecutionProvider"),
            )
            return synthesizer
        except Exception:
            logger.exception("interviewer_kokoro_failed")
    logger.info("interviewer_voice engine=piper voice=%s", piper_voice)
    return PiperSynthesizer(ensure_piper_voice(directory, piper_voice))


def prewarm(_process: JobProcess) -> None:
    """Load the speech models before a call arrives, so the first words are not delayed."""
    configure_logging()
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
        self.candidate_present = False
        self._barge = BargeMeter()
        self._tasks: set[asyncio.Task[None]] = set()

    def watch(self, room: rtc.Room) -> None:
        room.on("track_subscribed", self._on_track)
        room.on("participant_disconnected", self._on_leave)
        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.track is not None:
                    self._on_track(publication.track, publication, participant)

    def discard_pending(self) -> None:
        """Drop microphone audio captured before this listen. A departure notice stays."""
        departed = False
        while True:
            try:
                item = self.frames.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is None:
                departed = True
        if departed:
            self.frames.put_nowait(None)

    def take_frame(self, pcm: bytes) -> None:
        """Keep microphone audio only while the interviewer is quiet.

        Frames recorded during the question are the agent's own voice in the mic.
        Reading them later ends the turn before the candidate has spoken.
        """
        if self.speaking:
            if not self._barge.push(pcm):
                return
            self.interrupt.set()
            self.speaking = False
            self.capture = True
            self.discard_pending()
        else:
            self._barge.reset()
        if not self.capture:
            return
        self.frames.put_nowait(pcm)

    def _on_leave(self, participant: rtc.RemoteParticipant) -> None:
        if participant.identity == "candidate":
            self.candidate_present = False
            self.frames.put_nowait(None)

    def _on_track(self, track: rtc.Track, _publication: rtc.TrackPublication, participant: rtc.RemoteParticipant) -> None:
        if participant.identity != "candidate" or not _is_audio(track):
            return
        self.candidate_present = True
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
                self.take_frame(pcm)
        except Exception:
            logger.exception("interviewer_listen_failed")

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


def _with_bank(utterance: Utterance, bank: tuple[str, ...], transcript: str) -> Utterance:
    say = spoken_with_bank(utterance.say, utterance.asks, list(bank), transcript)
    if say == utterance.say:
        return utterance
    return Utterance(
        say=say,
        covered=utterance.covered,
        finished=utterance.finished,
        offer_quiz=utterance.offer_quiz,
        answered=utterance.answered,
        asks=utterance.asks,
        probe=utterance.probe,
    )


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
        bank = tuple(await list_question_texts(db))
        return Brief(
            candidate_name=row.candidate.full_name,
            job_title=row.candidate.version.job.title,
            company_name=settings.company_name,
            questions=tuple(questions),
            profile=cv_profile_text(row.candidate.full_name, raw),
            bank=bank,
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
    notes: set[asyncio.Task[None]] = set()
    warming = asyncio.create_task(_warm_clips(synthesizer, clips, (*ANSWER_FILLERS, *QUESTION_FILLERS, SORRY_LINE)))
    turns = 0
    failures = 0

    try:
        greeting = await _deliver(ctx, ear, recognizer, synthesizer, hello, slot["source"], clips)
        slot["source"] = greeting.source
        if greeting.heard is None and await _departed(ctx):
            return
        pending = greeting.heard or ""

        while True:
            if pending:
                heard = pending
                pending = ""
            else:
                heard = await _attend(ctx, ear, recognizer, lines[-1].removeprefix("recruiter: "))
            if heard is None:
                if await _departed(ctx):
                    break
                continue
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
                    if await _departed(ctx):
                        break
                    continue
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
                _keep_note(notes, asyncio.create_task(_record(ctx, "candidate", heard)))
                await _fill_gap(ctx, ear, plan_task, filler_line(kind, turns), slot, clips)
                utterance, agenda = await plan_task
                utterance = _with_bank(utterance, brief.bank, "\n".join(lines))
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
                if await _departed(ctx):
                    break
                continue
            if reply.heard:
                pending = reply.heard
                continue
            if utterance.finished:
                await _finish(ctx, ear, recognizer, synthesizer, planner, brief, slot, clips, lines)
                break
    finally:
        warming.cancel()
        if notes:
            await asyncio.gather(*list(notes), return_exceptions=True)
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
        if await _departed(ctx):
            return
        heard = ""
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
                if spoken.heard is None and await _departed(ctx):
                    return
    quiz = await _deliver(ctx, ear, recognizer, synthesizer, QUIZ_LINE, slot["source"], clips)
    slot["source"] = quiz.source
    await _publish(ctx, {"type": "quiz"}, topic="interview", identities=["candidate"])
    await asyncio.sleep(2)
    await close_interview_from_agent(ctx.room.name)


def _silence_held(last_voice_at: float, min_wall_s: float) -> bool:
    """True once the candidate has actually been quiet for the required pause."""
    if min_wall_s <= 0:
        return True
    return time.perf_counter() - last_voice_at >= min_wall_s


async def _listen(
    ear: CandidateEar,
    recognizer: WhisperRecognizer,
    last_spoken: str,
    *,
    on_hold: Callable[[], Awaitable[None]] | None = None,
    idle_seconds: float = _QUIET_LIMIT,
    silence_ms: int = _ANSWER_SILENCE_MS,
    short_silence_ms: int | None = _SHORT_SILENCE_MS,
    min_wall_s: float | None = None,
) -> str | None:
    def fresh_gate() -> SpeechGate:
        return SpeechGate(silence_ms=silence_ms, short_silence_ms=short_silence_ms)

    wall_s = silence_ms / 1000 if min_wall_s is None else min_wall_s
    gate = fresh_gate()
    started = time.perf_counter()
    last_voice_at = started
    peek_task: asyncio.Task[str] | None = None
    peek_audio: bytes | None = None
    while True:
        try:
            pcm = await asyncio.wait_for(ear.frames.get(), timeout=1.0)
        except TimeoutError:
            heard = _ready_early(peek_task, last_spoken)
            if heard and _silence_held(last_voice_at, wall_s):
                return heard
            if not gate.armed and time.perf_counter() - started >= idle_seconds:
                _forget_task(peek_task)
                return ""
            if time.perf_counter() - started >= _LISTEN_TIMEOUT:
                _forget_task(peek_task)
                return ""
            continue
        if pcm is None:
            _forget_task(peek_task)
            if getattr(ear, "candidate_present", False):
                continue
            return None
        if pcm16_rms(pcm) >= 0.02:
            last_voice_at = time.perf_counter()
        audio = gate.push(pcm)
        if audio is not None and not _silence_held(last_voice_at, wall_s):
            _forget_task(peek_task)
            peek_task = None
            peek_audio = None
            gate = fresh_gate()
            continue
        if audio is None:
            held = _silence_held(last_voice_at, wall_s)
            early = gate.early_audio(_EARLY_AFTER_MS, _EARLY_LONGEST_MS) if held else None
            if early is not None and peek_task is None:
                peek_audio = early
                peek_task = asyncio.create_task(_transcribe(recognizer, early))
            heard = _ready_early(peek_task, last_spoken)
            if heard and held:
                return heard
            if on_hold is not None and gate.wants_hold():
                await on_hold()
            if not gate.armed and time.perf_counter() - started >= idle_seconds:
                _forget_task(peek_task)
                return ""
            continue
        cleaned = await _finish_transcript(recognizer, audio, peek_task, peek_audio)
        peek_task = None
        peek_audio = None
        if cleaned and not echoes_prompt(cleaned, last_spoken):
            return cleaned
        gate = fresh_gate()
        started = time.perf_counter()


def _ready_early(task: asyncio.Task[str] | None, last_spoken: str) -> str:
    """A finished early transcript, when the words are already a complete short turn."""
    if task is None or not task.done():
        return ""
    try:
        text = task.result()
    except Exception:
        logger.exception("interviewer_early_transcript_failed")
        return ""
    cleaned = " ".join(text.split())
    if cleaned and ends_turn_early(cleaned) and not echoes_prompt(cleaned, last_spoken):
        logger.info("interviewer_turn_ended_early chars=%s", len(cleaned))
        return cleaned
    return ""


def _forget_task(task: asyncio.Task[str] | None) -> None:
    if task is None:
        return
    if task.done():
        _swallow_task(task)
        return
    task.add_done_callback(_swallow_task)


def _swallow_task(task: asyncio.Task[str]) -> None:
    try:
        task.result()
    except Exception:
        return


async def _finish_transcript(
    recognizer: WhisperRecognizer,
    audio: bytes,
    peek_task: asyncio.Task[str] | None,
    peek_audio: bytes | None,
) -> str:
    """Reuse the transcript taken during the pause when the candidate added only silence."""
    peeked = ""
    if peek_task is not None:
        try:
            peeked = await peek_task
        except Exception:
            logger.exception("interviewer_early_transcript_failed")
            peeked = ""
    if peeked and peek_audio is not None and continued_in_silence(peek_audio, audio):
        return " ".join(peeked.split())
    return await _transcribe(recognizer, audio)


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


@dataclass
class _SpokenLine:
    play: asyncio.Task[bool]
    worker: asyncio.Task[None]
    pieces: list[bytes]

    def audio(self) -> bytes:
        return b"".join(self.pieces)


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
    spoken: list[str] = []
    prefetch: asyncio.Task[bytes] | None = None
    try:
        for index, sentence in enumerate(sentences):
            nxt = sentences[index + 1] if index + 1 < len(sentences) else None
            worker: asyncio.Task[None] | None = None
            if prefetch is not None:
                audio = await prefetch
                prefetch = None
                if audio:
                    clips[sentence] = audio
                interrupted = await _play_audio(ear, source, audio)
            elif sentence in clips:
                interrupted = await _play_audio(ear, source, clips[sentence])
            else:
                line = _begin_line(ear, source, synthesizer, sentence)
                worker = line.worker
                if nxt is not None:
                    prefetch = asyncio.create_task(_prefetch_after(line.worker, synthesizer, nxt, clips))
                interrupted = await line.play
                await line.worker
                if line.audio():
                    clips[sentence] = line.audio()
            if not interrupted and nxt is not None and prefetch is None and nxt not in clips:
                prefetch = asyncio.create_task(_sentence_audio(synthesizer, nxt, clips))
            if interrupted:
                await _drop_prefetch(prefetch)
                if worker is not None:
                    await worker
                return Playback(source, True, " ".join(spoken), " ".join(sentences[index:]))
            spoken.append(sentence)
    finally:
        if prefetch is not None and not prefetch.done():
            await _drop_prefetch(prefetch)
    return Playback(source, False, text, "")


async def _prefetch_after(
    worker: asyncio.Task[None],
    synthesizer: SpeechSynthesizer,
    sentence: str,
    clips: dict[str, bytes],
) -> bytes:
    """Synthesize the next clause once this one has released the voice."""
    await worker
    if sentence in clips:
        return clips[sentence]
    return await _sentence_audio(synthesizer, sentence, clips)


async def _drop_prefetch(task: asyncio.Task[bytes] | None) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        return


def _begin_line(
    ear: CandidateEar,
    source: rtc.AudioSource,
    synthesizer: SpeechSynthesizer,
    sentence: str,
) -> _SpokenLine:
    """Start speaking as the first audio arrives, instead of waiting for the whole clause."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    pieces: list[bytes] = []

    def produce() -> None:
        try:
            for audio, rate in _utterance_pieces(synthesizer, sentence):
                pcm = _playback_pcm(audio, rate)
                if pcm:
                    pieces.append(pcm)
                    loop.call_soon_threadsafe(queue.put_nowait, pcm)
        except Exception:
            logger.exception("interviewer_synth_failed")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    worker = asyncio.create_task(asyncio.to_thread(produce))
    play = asyncio.create_task(_play_queued(ear, source, queue))
    return _SpokenLine(play, worker, pieces)


def _utterance_pieces(synthesizer: SpeechSynthesizer, sentence: str):
    pieces = getattr(synthesizer, "iter_pcm", None)
    if callable(pieces):
        yield from pieces(sentence)
        return
    audio, rate = synthesizer.synthesize(sentence)
    if audio:
        yield audio, rate


async def _sentence_audio(synthesizer: SpeechSynthesizer, sentence: str, clips: dict[str, bytes]) -> bytes:
    cached = clips.get(sentence)
    if cached is not None:
        return cached
    try:
        audio, rate = await asyncio.to_thread(synthesizer.synthesize, sentence)
    except Exception:
        logger.exception("interviewer_synth_failed")
        return b""
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


async def _play_queued(ear: CandidateEar, source: rtc.AudioSource, queue: asyncio.Queue[bytes | None]) -> bool:
    """Play chunks as they arrive. Return True when the candidate talks over the line."""
    ear.interrupt.clear()
    try:
        while True:
            chunk = await _chunk_or_stop(ear, queue)
            if chunk is None:
                if ear.interrupt.is_set():
                    source.clear_queue()
                    return True
                break
            ear.speaking = True
            for frame in split_pcm16(chunk, max(1, _PLAYBACK_RATE // 50)):
                if ear.interrupt.is_set():
                    source.clear_queue()
                    return True
                await source.capture_frame(rtc.AudioFrame(frame, _PLAYBACK_RATE, 1, len(frame) // 2))
        if ear.interrupt.is_set():
            source.clear_queue()
            return True
        await source.wait_for_playout()
    finally:
        _release_mic(ear)
    return ear.interrupt.is_set()


def _release_mic(ear: CandidateEar) -> None:
    """The question is over. Forget audio from while the agent was speaking."""
    interrupted = ear.interrupt.is_set()
    ear.speaking = False
    if not interrupted:
        ear.discard_pending()


async def _chunk_or_stop(ear: CandidateEar, queue: asyncio.Queue[bytes | None]) -> bytes | None:
    incoming = asyncio.create_task(queue.get())
    stopped = asyncio.create_task(ear.interrupt.wait())
    await asyncio.wait({incoming, stopped}, return_when=asyncio.FIRST_COMPLETED)
    chunk: bytes | None = None
    if incoming.done() and not incoming.cancelled():
        try:
            chunk = incoming.result()
        except Exception:
            chunk = None
    for task in (incoming, stopped):
        if chunk is not None and task is incoming:
            continue
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            continue
    return chunk


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
        _release_mic(ear)
    return ear.interrupt.is_set()


def _keep_note(notes: set[asyncio.Task[None]], task: asyncio.Task[None]) -> None:
    notes.add(task)
    task.add_done_callback(notes.discard)


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
    silence_ms: int = _ANSWER_SILENCE_MS,
    short_silence_ms: int | None = _SHORT_SILENCE_MS,
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


def _candidate_in_room(room: rtc.Room) -> bool:
    return any(participant.identity == "candidate" for participant in room.remote_participants.values())


async def _departed(ctx: JobContext) -> bool:
    """The candidate is gone. A reconnect while the greeting plays is not a goodbye."""
    if _candidate_in_room(ctx.room):
        logger.info("interviewer_reconnect_ignored")
        return False
    await close_interview_from_agent(ctx.room.name)
    return True


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
    configure_logging()
    cli.run_app(server)
