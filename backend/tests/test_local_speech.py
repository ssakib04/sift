import math
import os
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.local_speech import (
    KOKORO_FILES,
    BargeMeter,
    SpeechGate,
    ensure_kokoro_files,
    float_array_to_pcm16,
    continued_in_silence,
    kokoro_language,
    onnx_session_plan,
    prepare_speech_runtime,
    resolve_whisper_device,
    synthesize_pieces,
    whisper_model_kwargs,
    whisper_transcribe_kwargs,
    is_audio_kind,
    is_video_kind,
    join_segment_text,
    pcm16_rms,
    float_to_pcm16,
    pcm16_to_float,
    pcm_from_chunks,
    resample_linear,
    split_pcm16,
    speech_hints,
    trim_trailing_silence,
    voice_paths,
)


def _tone(samples: int, rate: int, amplitude: float) -> bytes:
    pcm = bytearray()
    for index in range(samples):
        value = int(amplitude * 32767 * math.sin(2 * math.pi * 440 * index / rate))
        pcm += struct.pack("<h", value)
    return bytes(pcm)


def test_speech_hints_keep_checklist_tools_and_cv_names() -> None:
    hints = speech_hints(
        ["Does the candidate have experience working with PostgreSQL databases?"],
        "Kazi Rafiul Kader\nHarbor Ledger\nBackend engineer in Dhaka",
    )
    assert "PostgreSQL" in hints
    assert "Dhaka" in hints
    assert "Harbor Ledger" in hints


def test_livekit_audio_kind_is_the_integer_one() -> None:
    class _Named:
        name = "KIND_AUDIO"

    assert is_audio_kind(1) is True
    assert is_audio_kind(_Named()) is True
    assert is_audio_kind(2) is False
    assert is_audio_kind("video") is False


def test_rms_is_silent_for_zeros_and_loud_for_a_tone() -> None:
    assert pcm16_rms(b"") == 0
    assert pcm16_rms(b"\x00\x00" * 160) == 0
    assert pcm16_rms(_tone(1600, 16000, 0.5)) > 0.2


def test_float_conversion_and_resample_keep_the_duration() -> None:
    pcm = _tone(16000, 16000, 0.25)
    samples = pcm16_to_float(pcm)
    assert len(samples) == 16000
    assert max(samples) > 0.2
    assert pcm16_to_float(float_to_pcm16([0.5, -0.5]))[0] > 0.4
    stretched = resample_linear(samples[:1600], 16000, 8000)
    assert len(stretched) == 800


def test_split_pcm16_pads_the_last_frame() -> None:
    frames = split_pcm16(b"\x01\x00" * 5, 4)
    assert len(frames) == 2
    assert len(frames[0]) == 8
    assert len(frames[1]) == 8
    assert frames[1].endswith(b"\x00\x00")


def test_speech_gate_returns_audio_after_a_pause() -> None:
    gate = SpeechGate(sample_rate=16000, speech_ms=200, silence_ms=400, max_ms=5000)
    assert gate.push(b"\x00\x00" * 1600) is None
    heard = None
    for _ in range(10):
        heard = gate.push(_tone(1600, 16000, 0.4))
        if heard is not None:
            break
    assert heard is None
    finished = None
    for _ in range(8):
        finished = gate.push(b"\x00\x00" * 1600)
        if finished is not None:
            break
    assert finished is not None
    assert pcm16_rms(finished) > 0.05


def test_a_short_answer_closes_sooner_than_a_story() -> None:
    short = SpeechGate(sample_rate=1000)
    assert short.push(_tone(400, 1000, 0.4)) is None
    assert short.push(b"\x00\x00" * 800) is None
    assert short.push(b"\x00\x00" * 200) is not None

    story = SpeechGate(sample_rate=1000)
    assert story.push(_tone(3000, 1000, 0.4)) is None
    assert story.push(b"\x00\x00" * 1200) is None
    assert story.wants_hold() is True
    assert story.wants_hold() is False
    assert story.push(b"\x00\x00" * 900) is None
    assert story.push(b"\x00\x00" * 200) is not None

    ongoing = SpeechGate(sample_rate=1000)
    for _ in range(4):
        assert ongoing.push(_tone(60_000, 1000, 0.4)) is None
    assert ongoing.push(_tone(60_000, 1000, 0.4)) is not None


def test_silence_after_a_peek_is_the_same_utterance() -> None:
    prefix = _tone(800, 16000, 0.4)
    assert continued_in_silence(prefix, prefix + (b"\x00\x00" * 1600))
    assert not continued_in_silence(prefix, prefix + _tone(800, 16000, 0.4))


def test_cpu_whisper_is_capped_and_cuda_is_left_to_the_device() -> None:
    cpu = whisper_model_kwargs("cpu", 4)
    assert cpu["cpu_threads"] == 4
    assert cpu["num_workers"] == 1
    assert cpu["compute_type"] == "int8"
    cuda = whisper_model_kwargs("cuda", 4)
    assert "cpu_threads" not in cuda
    assert cuda["device"] == "cuda"
    assert cuda["compute_type"] == "float16"


def test_transcription_skips_the_extra_voice_activity_pass() -> None:
    options = whisper_transcribe_kwargs("FastAPI")
    assert options["vad_filter"] is False
    assert options["initial_prompt"] == "FastAPI"
    assert options["hotwords"] == "FastAPI"


def test_onnx_uses_cuda_when_that_provider_is_present() -> None:
    providers, threads = onnx_session_plan(("CUDAExecutionProvider", "CPUExecutionProvider"), 4)
    assert providers[0] == "CUDAExecutionProvider"
    assert threads == 1
    cpu_providers, cpu_threads = onnx_session_plan(("CPUExecutionProvider",), 4)
    assert cpu_providers == ("CPUExecutionProvider",)
    assert cpu_threads == 4


def test_speech_runtime_caps_unset_thread_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    monkeypatch.setenv("MKL_NUM_THREADS", "8")
    prepare_speech_runtime(4)
    assert os.environ["OMP_NUM_THREADS"] == "4"
    assert os.environ["MKL_NUM_THREADS"] == "8"


def test_whisper_device_keeps_an_explicit_choice() -> None:
    assert resolve_whisper_device("cpu") == "cpu"
    assert resolve_whisper_device(" CUDA ") == "cuda"


def test_auto_whisper_uses_cuda_only_when_a_device_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 1))
    assert resolve_whisper_device("auto") == "cuda"
    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 0))
    assert resolve_whisper_device("auto") == "cpu"

    def unavailable() -> int:
        raise RuntimeError("no gpu")

    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(get_cuda_device_count=unavailable))
    assert resolve_whisper_device("auto") == "cpu"


def test_streamed_speech_yields_each_chunk() -> None:
    class Engine:
        def create_stream(self, text: str, voice: str, speed: float, lang: str):
            yield [0.0, 0.5], 24000
            yield [-0.25], 24000

        def create(self, text: str, voice: str, speed: float, lang: str):
            raise AssertionError(text)

    pieces = list(synthesize_pieces(Engine(), "Hello there.", voice="af_heart", speed=1.08, language="en-us"))
    assert len(pieces) == 2
    assert pieces[0][1] == 24000
    assert pieces[0][0]


def test_speech_without_a_stream_returns_one_piece() -> None:
    class Engine:
        def create(self, text: str, voice: str, speed: float, lang: str):
            return [0.2, -0.2], 24000

    pieces = list(synthesize_pieces(Engine(), "Hello.", voice="af_heart", speed=1.08, language="en-us"))
    assert len(pieces) == 1
    assert pieces[0][1] == 24000


def test_kokoro_voice_language_follows_the_voice_prefix() -> None:
    assert kokoro_language("af_heart") == "en-us"
    assert kokoro_language("bf_emma") == "en-gb"


def test_kokoro_float_audio_becomes_clipped_pcm16() -> None:
    pcm = float_array_to_pcm16([0.0, 0.5, 2.0, -2.0])
    values = struct.unpack("<4h", pcm)
    assert values[0] == 0
    assert 16000 < values[1] < 16500
    assert values[2] == 32767
    assert values[3] == -32767


def test_kokoro_files_are_reused_once_downloaded(tmp_path: Path) -> None:
    for name, _url in KOKORO_FILES.values():
        (tmp_path / name).write_bytes(b"model")
    model, voices = ensure_kokoro_files(tmp_path)
    assert model.name.endswith(".onnx")
    assert voices.name.endswith(".bin")


def test_livekit_video_kind_is_the_integer_two() -> None:
    class _Named:
        name = "KIND_VIDEO"

    assert is_video_kind(2) is True
    assert is_video_kind(_Named()) is True
    assert is_video_kind(1) is False
    assert is_video_kind("audio") is False


def test_a_short_turn_can_be_read_early_once_per_pause() -> None:
    gate = SpeechGate(sample_rate=1000, silence_ms=4800, short_silence_ms=3200)
    assert gate.push(_tone(1500, 1000, 0.4)) is None
    assert gate.early_audio(900, 6000) is None
    assert gate.push(b"\x00\x00" * 1000) is None
    early = gate.early_audio(900, 6000)
    assert early is not None
    assert pcm16_rms(early) > 0.05
    assert gate.early_audio(900, 6000) is None
    assert gate.push(_tone(500, 1000, 0.4)) is None
    assert gate.push(b"\x00\x00" * 1000) is None
    assert gate.early_audio(900, 6000) is not None


def test_a_long_turn_is_never_read_early() -> None:
    gate = SpeechGate(sample_rate=1000, silence_ms=4800, short_silence_ms=3200)
    assert gate.push(_tone(7000, 1000, 0.4)) is None
    assert gate.push(b"\x00\x00" * 1000) is None
    assert gate.early_audio(900, 6000) is None


def test_trailing_silence_is_trimmed_before_transcription() -> None:
    speech = _tone(1600, 16000, 0.4)
    quiet = b"\x00\x00" * 16000
    trimmed = trim_trailing_silence(speech + quiet, 16000)
    assert len(trimmed) < len(speech) + 16000
    assert len(trimmed) > len(speech)


def test_barge_meter_needs_a_sustained_loud_stretch() -> None:
    meter = BargeMeter(sample_rate=16000, threshold=0.05, hold_ms=200)
    assert meter.push(_tone(1600, 16000, 0.01)) is False
    assert meter.push(_tone(1600, 16000, 0.4)) is False
    assert meter.push(_tone(1600, 16000, 0.4)) is True
    meter.reset()
    assert meter.push(_tone(1600, 16000, 0.4)) is False


def test_segment_text_and_piper_chunks() -> None:
    class _Segment:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Chunk:
        def __init__(self) -> None:
            self.audio_int16_bytes = b"\x01\x00\x02\x00"
            self.sample_rate = 22050

    assert join_segment_text([_Segment(" Hello "), _Segment(" "), _Segment("there")]) == "Hello there"
    audio, rate = pcm_from_chunks([_Chunk(), b"\x03\x00"])
    assert audio == b"\x01\x00\x02\x00\x03\x00"
    assert rate == 22050


def test_voice_paths_use_the_local_directory() -> None:
    model, config = voice_paths(Path("/voices"), "en_US-lessac-medium")
    assert model.name == "en_US-lessac-medium.onnx"
    assert config.name == "en_US-lessac-medium.onnx.json"


def test_voice_paths_reject_an_unknown_voice() -> None:
    with pytest.raises(ValueError):
        voice_paths(Path("/voices"), "other")
