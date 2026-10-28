import asyncio
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import interviewer_worker
from app.interviewer_worker import CandidateEar, _candidate_camera, _fill_gap, _listen, _sentence_audio, _voice


def _room(*participants: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(remote_participants={str(index): person for index, person in enumerate(participants)})


def _person(identity: str, *publications: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        identity=identity,
        track_publications={str(index): publication for index, publication in enumerate(publications)},
    )


def test_piper_speaks_when_kokoro_cannot_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _broken(_directory: Path) -> tuple[Path, Path]:
        raise OSError("offline")

    class _Piper:
        def __init__(self, model: Path) -> None:
            self.model = model

    monkeypatch.setattr(interviewer_worker, "ensure_kokoro_files", _broken)
    monkeypatch.setattr(interviewer_worker, "ensure_piper_voice", lambda directory, voice: directory / f"{voice}.onnx")
    monkeypatch.setattr(interviewer_worker, "PiperSynthesizer", _Piper)

    voice = _voice(tmp_path, "kokoro", "af_heart", "en_GB-cori-medium")
    assert isinstance(voice, _Piper)
    assert voice.model.name == "en_GB-cori-medium.onnx"


@pytest.mark.asyncio
async def test_a_speech_outage_returns_silence_instead_of_ending_the_call() -> None:
    class _Broken:
        def synthesize(self, _text: str) -> tuple[bytes, int]:
            raise RuntimeError("groq speech failed status=400")

    assert await _sentence_audio(_Broken(), "Hello there.", {}) == b""


def test_a_groq_key_skips_the_local_speech_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(interviewer_worker, "_engines", None)

    def _settings() -> SimpleNamespace:
        return SimpleNamespace(
            groq_api_key="test-key",
            groq_stt_model="whisper-large-v3-turbo",
            groq_tts_model="canopylabs/orpheus-v1-english",
            groq_tts_voice="autumn",
        )

    monkeypatch.setattr(interviewer_worker, "get_settings", _settings)
    monkeypatch.setattr(
        interviewer_worker,
        "prepare_speech_runtime",
        lambda _threads: (_ for _ in ()).throw(AssertionError("local speech should stay unloaded")),
    )

    recognizer, synthesizer = interviewer_worker.speech_engines()
    assert isinstance(recognizer, interviewer_worker.GroqRecognizer)
    assert isinstance(synthesizer, interviewer_worker.GroqSynthesizer)
    assert synthesizer.provider == "groq"


def test_kokoro_is_used_when_it_loads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Kokoro:
        def __init__(self, model: Path, voices: Path, voice: str, speed: float = 1.08, cpu_threads: int = 4) -> None:
            self.voice = voice
            self.speed = speed
            self.cpu_threads = cpu_threads

    monkeypatch.setattr(interviewer_worker, "ensure_kokoro_files", lambda directory: (directory / "m", directory / "v"))
    monkeypatch.setattr(interviewer_worker, "KokoroSynthesizer", _Kokoro)

    voice = _voice(tmp_path, "kokoro", "af_heart", "en_GB-cori-medium")
    assert isinstance(voice, _Kokoro)
    assert voice.voice == "af_heart"
    assert voice.speed == 1.08


def test_the_camera_is_read_from_the_candidate_publications() -> None:
    microphone = SimpleNamespace(kind=1, muted=False)
    live_camera = SimpleNamespace(kind=2, muted=False)
    muted_camera = SimpleNamespace(kind=2, muted=True)

    assert _candidate_camera(_room(_person("candidate", microphone, live_camera))) is True
    assert _candidate_camera(_room(_person("candidate", microphone, muted_camera))) is False
    assert _candidate_camera(_room(_person("candidate", microphone))) is False
    assert _candidate_camera(_room(_person("recruiter", live_camera))) is None


@pytest.mark.asyncio
async def test_a_quick_reply_plays_no_filler(monkeypatch: pytest.MonkeyPatch) -> None:
    played: list[bytes] = []

    async def _play(_ear: object, _source: object, audio: bytes) -> bool:
        played.append(audio)
        return False

    monkeypatch.setattr(interviewer_worker, "_play_audio", _play)

    async def _quick() -> str:
        return "ready"

    task = asyncio.create_task(_quick())
    await _fill_gap(SimpleNamespace(), SimpleNamespace(), task, "Right.", {"source": object()}, {"Right.": b"\x01\x00"})
    assert played == []


@pytest.mark.asyncio
async def test_a_slow_reply_plays_the_filler_first(monkeypatch: pytest.MonkeyPatch) -> None:
    played: list[bytes] = []

    async def _play(_ear: object, _source: object, audio: bytes) -> bool:
        played.append(audio)
        return False

    monkeypatch.setattr(interviewer_worker, "_play_audio", _play)
    monkeypatch.setattr(interviewer_worker, "_FILLER_AFTER", 0.01)

    async def _slow() -> str:
        await asyncio.sleep(0.2)
        return "ready"

    task = asyncio.create_task(_slow())
    await _fill_gap(SimpleNamespace(), SimpleNamespace(), task, "Right.", {"source": object()}, {"Right.": b"\x01\x00"})
    assert played == [b"\x01\x00"]
    assert await task == "ready"


def test_audio_during_the_question_is_not_treated_as_an_answer() -> None:
    ear = CandidateEar()
    ear.speaking = True
    ear.frames.put_nowait(_pcm(1600, 1000))
    ear.take_frame(_pcm(1600, 8000))
    assert ear.frames.get_nowait() == _pcm(1600, 1000)
    assert ear.frames.empty()
    assert ear.interrupt.is_set() is False


def test_talking_over_the_question_starts_a_fresh_listen() -> None:
    ear = CandidateEar()
    ear.speaking = True
    ear.frames.put_nowait(_pcm(1600, 1000))
    ear.take_frame(_pcm(3200, 8000))
    assert ear.interrupt.is_set() is True
    assert ear.speaking is False
    assert ear.frames.get_nowait() == _pcm(3200, 8000)
    assert ear.frames.empty()


def test_a_departure_survives_clearing_the_microphone() -> None:
    ear = CandidateEar()
    ear.frames.put_nowait(_pcm(1600, 8000))
    ear.frames.put_nowait(None)
    ear.discard_pending()
    assert ear.frames.get_nowait() is None
    assert ear.frames.empty()


def _pcm(samples: int, value: int) -> bytes:
    return struct.pack("<h", value) * samples


class _Ear:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames: asyncio.Queue[bytes | None] = asyncio.Queue()
        for frame in frames:
            self.frames.put_nowait(frame)


class _Recognizer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0
        self.samples = 0

    def transcribe(self, pcm: bytes, rate: int) -> str:
        self.calls += 1
        self.samples = len(pcm) // 2
        return self.text


@pytest.mark.asyncio
async def test_a_finished_answer_waits_through_four_seconds_of_silence() -> None:
    recognizer = _Recognizer("I led the migration.")
    ear = _Ear([_pcm(6400, 8000), _pcm(64000, 0)])
    heard = await asyncio.wait_for(
        _listen(ear, recognizer, "Tell me about a project you shipped.", min_wall_s=0),
        timeout=3,
    )
    assert heard == "I led the migration."
    assert recognizer.calls == 1


@pytest.mark.asyncio
async def test_a_buffered_pause_does_not_end_the_turn() -> None:
    recognizer = _Recognizer("I led the migration.")
    ear = _Ear([_pcm(6400, 8000), _pcm(64000, 0)])
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            _listen(ear, recognizer, "Tell me about a project you shipped."),
            timeout=0.4,
        )
    assert recognizer.calls == 0


@pytest.mark.asyncio
async def test_a_one_second_pause_does_not_end_the_answer() -> None:
    recognizer = _Recognizer("I led the migration and then checked the logs.")
    ear = _Ear([_pcm(6400, 8000), _pcm(16000, 0), _pcm(6400, 8000), _pcm(64000, 0)])
    heard = await asyncio.wait_for(
        _listen(ear, recognizer, "Tell me about a project you shipped.", min_wall_s=0),
        timeout=3,
    )
    assert heard == "I led the migration and then checked the logs."
    assert recognizer.calls == 1
    assert recognizer.samples > 6400 + 16000


@pytest.mark.asyncio
async def test_a_reconnect_blip_does_not_end_the_listen() -> None:
    recognizer = _Recognizer("I led the migration.")
    ear = _Ear([None, _pcm(6400, 8000), _pcm(64000, 0)])
    ear.candidate_present = True
    heard = await asyncio.wait_for(
        _listen(ear, recognizer, "Tell me about a project you shipped.", min_wall_s=0),
        timeout=3,
    )
    assert heard == "I led the migration."


@pytest.mark.asyncio
async def test_the_candidate_leaving_ends_the_listen() -> None:
    recognizer = _Recognizer("I led the migration.")
    ear = _Ear([None])
    ear.candidate_present = False
    heard = await asyncio.wait_for(_listen(ear, recognizer, "Tell me about a project you shipped."), timeout=3)
    assert heard is None
    assert recognizer.calls == 0


@pytest.mark.asyncio
async def test_a_pause_reuses_the_transcript_taken_during_the_silence() -> None:
    recognizer = _Recognizer("I would start with the logs")
    ear = _Ear([_pcm(6400, 8000), _pcm(48000, 0), _pcm(16000, 0)])
    heard = await asyncio.wait_for(_listen(ear, recognizer, "Where would you start?", min_wall_s=0), timeout=3)
    assert heard == "I would start with the logs"
    assert recognizer.calls == 1
