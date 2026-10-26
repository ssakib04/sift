import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import interviewer_worker
from app.interviewer_worker import _candidate_camera, _fill_gap, _voice


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


def test_kokoro_is_used_when_it_loads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Kokoro:
        def __init__(self, model: Path, voices: Path, voice: str) -> None:
            self.voice = voice

    monkeypatch.setattr(interviewer_worker, "ensure_kokoro_files", lambda directory: (directory / "m", directory / "v"))
    monkeypatch.setattr(interviewer_worker, "KokoroSynthesizer", _Kokoro)

    voice = _voice(tmp_path, "kokoro", "af_heart", "en_GB-cori-medium")
    assert isinstance(voice, _Kokoro)
    assert voice.voice == "af_heart"


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
