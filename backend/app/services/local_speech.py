import array
import logging
import os
import re
import struct
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

VOICE_FILES = {
    "en_GB-cori-medium": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/medium/en_GB-cori-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/cori/medium/en_GB-cori-medium.onnx.json",
    ),
    "en_US-lessac-medium": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    ),
}


def is_audio_kind(kind: object) -> bool:
    """LiveKit reports a microphone as the integer 1, not the word audio."""
    if kind == 1:
        return True
    name = str(getattr(kind, "name", kind)).upper()
    return "AUDIO" in name


def is_video_kind(kind: object) -> bool:
    """LiveKit reports a camera as the integer 2, not the word video."""
    if kind == 2:
        return True
    name = str(getattr(kind, "name", kind)).upper()
    return "VIDEO" in name


def pcm16_rms(pcm: bytes) -> float:
    """Root-mean-square loudness of little-endian 16-bit audio, from 0 to about 1."""
    count = len(pcm) // 2
    if count == 0:
        return 0.0
    total = 0.0
    for offset in range(0, count * 2, 2):
        sample = int.from_bytes(pcm[offset : offset + 2], "little", signed=True) / 32768
        total += sample * sample
    return (total / count) ** 0.5


def continued_in_silence(prefix: bytes, audio: bytes, threshold: float = 0.02) -> bool:
    """True when audio is the prefix plus quiet, so the prefix transcript still covers it."""
    if not prefix or len(audio) < len(prefix) or not audio.startswith(prefix):
        return False
    extra = audio[len(prefix) :]
    if len(extra) < 2:
        return True
    return pcm16_rms(extra) < threshold


def prepare_speech_runtime(cpu_threads: int = 4) -> None:
    """Keep math libraries on a few cores so the interview does not take the whole machine."""
    threads = str(cpu_threads if cpu_threads > 0 else 4)
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(name, threads)


def onnx_providers() -> tuple[str, ...]:
    """CUDA when this process can see it, otherwise the CPU provider."""
    try:
        import onnxruntime as ort

        available = ort.get_available_providers()
    except Exception:
        return ("CPUExecutionProvider",)
    if isinstance(available, (list, tuple)) and "CUDAExecutionProvider" in available:
        return ("CUDAExecutionProvider", "CPUExecutionProvider")
    return ("CPUExecutionProvider",)


def onnx_session_plan(
    available: tuple[str, ...],
    cpu_threads: int = 4,
) -> tuple[tuple[str, ...], int]:
    """Providers and intra-op threads for one ONNX session. GPU sessions leave the CPU pool small."""
    if "CUDAExecutionProvider" in available:
        return (("CUDAExecutionProvider", "CPUExecutionProvider"), 1)
    threads = cpu_threads if cpu_threads > 0 else 4
    return (("CPUExecutionProvider",), threads)


def whisper_model_kwargs(device: str, cpu_threads: int = 4) -> dict[str, object]:
    """Load options for faster-whisper. CPU work is capped; CUDA is used when the device is cuda."""
    options: dict[str, object] = {
        "device": device,
        "compute_type": "int8" if device == "cpu" else "float16",
    }
    if device == "cpu":
        options["cpu_threads"] = cpu_threads if cpu_threads > 0 else 4
        options["num_workers"] = 1
    return options


def whisper_transcribe_kwargs(prompt: str) -> dict[str, object]:
    """Decode options for one answer. The speech gate already removed the silence."""
    cleaned = prompt.strip()
    return {
        "language": "en",
        "vad_filter": False,
        "beam_size": 1,
        "best_of": 1,
        "condition_on_previous_text": False,
        "without_timestamps": True,
        "initial_prompt": cleaned or None,
        "hotwords": cleaned or None,
    }


def resolve_whisper_device(requested: str) -> str:
    """Use CUDA when the machine has it. An explicit cpu or cuda choice is left alone."""
    choice = requested.strip().lower() or "cpu"
    if choice != "auto":
        return choice
    try:
        import ctranslate2

        count = ctranslate2.get_cuda_device_count()
    except Exception:
        return "cpu"
    return "cuda" if isinstance(count, int) and count > 0 else "cpu"


def pcm16_to_float(pcm: bytes) -> list[float]:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if sys.byteorder != "little":
        samples.byteswap()
    return [sample / 32768.0 for sample in samples]


def float_to_pcm16(samples: list[float]) -> bytes:
    pcm = bytearray()
    for sample in samples:
        value = max(-32768, min(32767, int(sample * 32767)))
        pcm += struct.pack("<h", value)
    return bytes(pcm)


def resample_linear(samples: list[float], source_rate: int, target_rate: int) -> list[float]:
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("Sample rates must be positive.")
    if source_rate == target_rate or not samples:
        return list(samples)
    target_length = max(1, int(len(samples) * target_rate / source_rate))
    stretched: list[float] = []
    last = len(samples) - 1
    for index in range(target_length):
        position = index * source_rate / target_rate
        left = min(int(position), last)
        right = min(left + 1, last)
        mix = position - left
        stretched.append(samples[left] * (1 - mix) + samples[right] * mix)
    return stretched


def split_pcm16(pcm: bytes, samples_per_frame: int) -> list[bytes]:
    if samples_per_frame <= 0:
        raise ValueError("A frame must contain samples.")
    width = samples_per_frame * 2
    aligned = pcm[: len(pcm) - (len(pcm) % 2)]
    frames: list[bytes] = []
    for offset in range(0, len(aligned), width):
        frame = aligned[offset : offset + width]
        if len(frame) < width:
            frame = frame + bytes(width - len(frame))
        frames.append(frame)
    return frames


def join_segment_text(segments: Iterable[object]) -> str:
    parts: list[str] = []
    for segment in segments:
        text = getattr(segment, "text", "")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return " ".join(parts)


def pcm_from_chunks(chunks: Iterable[object]) -> tuple[bytes, int]:
    """Read Piper's chunk objects, or raw PCM bytes, into one buffer and a sample rate."""
    pieces: list[bytes] = []
    rate = 22050
    for chunk in chunks:
        if isinstance(chunk, bytes):
            pieces.append(chunk)
            continue
        audio = getattr(chunk, "audio_int16_bytes", None)
        if isinstance(audio, bytes):
            pieces.append(audio)
        sample_rate = getattr(chunk, "sample_rate", None)
        if isinstance(sample_rate, int) and sample_rate > 0:
            rate = sample_rate
    return b"".join(pieces), rate


class SpeechGate:
    """Collect one answer, closing a short reply sooner than a story.

    A new sound resets the wait. A long answer can take a thinking pause.
    The answer stays open for up to five minutes.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.02,
        speech_ms: int = 240,
        silence_ms: int = 2200,
        short_silence_ms: int | None = None,
        short_speech_ms: int = 2500,
        hold_ms: int = 1200,
        max_ms: int = 300_000,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("Sample rate must be positive.")
        self.sample_rate = sample_rate
        self.threshold = threshold
        self._speech_needed = sample_rate * speech_ms // 1000
        self._long_silence = sample_rate * silence_ms // 1000
        resolved_short = min(900, silence_ms) if short_silence_ms is None else short_silence_ms
        self._short_silence = sample_rate * resolved_short // 1000
        self._short_speech = sample_rate * short_speech_ms // 1000
        self._hold_at = sample_rate * hold_ms // 1000
        self._max_samples = sample_rate * max_ms // 1000
        self._speech = 0
        self._voiced = 0
        self._silence = 0
        self._armed = False
        self._hold_sent = False
        self._peeked = False
        self._chunks: list[bytes] = []
        self._samples = 0

    @property
    def armed(self) -> bool:
        return self._armed

    def early_audio(self, after_ms: int, longest_ms: int) -> bytes | None:
        """The turn so far, once per pause, so a short question can be answered before the full wait.

        Only a short turn qualifies. Speech after the pause makes the next pause eligible again.
        """
        if self._peeked or not self._armed:
            return None
        if self._voiced > self.sample_rate * longest_ms // 1000:
            return None
        if self._silence < self.sample_rate * after_ms // 1000:
            return None
        self._peeked = True
        return b"".join(self._chunks)

    def wants_hold(self) -> bool:
        """True once, when a long answer has paused long enough for a listening sound."""
        if self._hold_sent or not self._armed or self._voiced < self._short_speech:
            return False
        if self._silence < self._hold_at:
            return False
        self._hold_sent = True
        return True

    def push(self, pcm: bytes) -> bytes | None:
        samples = len(pcm) // 2
        if samples == 0:
            return None
        self._chunks.append(pcm[: samples * 2])
        self._samples += samples
        if pcm16_rms(pcm) >= self.threshold:
            self._speech += samples
            self._silence = 0
            self._peeked = False
            if not self._armed and self._speech >= self._speech_needed:
                self._armed = True
                self._voiced = self._speech
            elif self._armed:
                self._voiced += samples
        elif self._armed:
            self._silence += samples
        needed = self._short_silence if self._voiced < self._short_speech else self._long_silence
        if self._armed and (self._silence >= needed or self._samples >= self._max_samples):
            return self._take()
        if not self._armed and self._samples > self.sample_rate * 3:
            self._chunks = self._chunks[-8:]
            self._samples = sum(len(chunk) // 2 for chunk in self._chunks)
            self._speech = 0
        return None

    def _take(self) -> bytes:
        audio = b"".join(self._chunks)
        self._chunks = []
        self._samples = 0
        self._speech = 0
        self._voiced = 0
        self._silence = 0
        self._armed = False
        self._hold_sent = False
        self._peeked = False
        return audio


class BargeMeter:
    """Notice when the candidate talks over the interviewer for long enough to interrupt."""

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.04, hold_ms: int = 200) -> None:
        self.sample_rate = sample_rate
        self.threshold = threshold
        self._hold_samples = sample_rate * hold_ms // 1000
        self._loud = 0

    def push(self, pcm: bytes) -> bool:
        samples = len(pcm) // 2
        if samples == 0:
            return False
        if pcm16_rms(pcm) >= self.threshold:
            self._loud += samples
        else:
            self._loud = 0
        return self._loud >= self._hold_samples

    def reset(self) -> None:
        self._loud = 0


def voice_paths(directory: Path, voice: str) -> tuple[Path, Path]:
    if voice not in VOICE_FILES:
        raise ValueError(f"Unsupported local voice: {voice}")
    return directory / f"{voice}.onnx", directory / f"{voice}.onnx.json"


def ensure_piper_voice(directory: Path, voice: str) -> Path:
    """Keep the Piper voice on disk. The weights are downloaded once, then synthesis is local."""
    model_path, config_path = voice_paths(directory, voice)
    model_url, config_url = VOICE_FILES[voice]
    directory.mkdir(parents=True, exist_ok=True)
    if not model_path.exists():
        _download(model_url, model_path)
    if not config_path.exists():
        _download(config_url, config_path)
    return model_path


def _download(url: str, path: Path) -> None:
    import httpx

    temporary = path.with_suffix(path.suffix + ".part")
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
    temporary.replace(path)


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Return 16-bit mono PCM for the text and its sample rate."""


KOKORO_FILES = {
    "model": (
        "kokoro-v1.0.int8.onnx",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx",
    ),
    "voices": (
        "voices-v1.0.bin",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
    ),
}
_KOKORO_RATE = 24000


def ensure_kokoro_files(directory: Path) -> tuple[Path, Path]:
    """Keep the Kokoro model and voices on disk. They are downloaded once, then synthesis is local."""
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for key in ("model", "voices"):
        name, url = KOKORO_FILES[key]
        path = directory / name
        if not path.exists():
            _download(url, path)
        paths.append(path)
    return paths[0], paths[1]


def kokoro_language(voice: str) -> str:
    """Kokoro voices starting with b are British English. The rest used here are American English."""
    return "en-gb" if voice.startswith("b") else "en-us"


def float_array_to_pcm16(samples: object) -> bytes:
    import numpy as np

    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767).astype("<i2").tobytes()


def synthesize_pieces(
    engine: object,
    text: str,
    *,
    voice: str,
    speed: float,
    language: str,
) -> Iterator[tuple[bytes, int]]:
    """Yield PCM as Kokoro produces it. A model without streaming returns one piece."""
    spoken = " ".join(text.split())
    if not spoken:
        return
    stream = getattr(engine, "create_stream", None)
    yielded = False
    if callable(stream):
        try:
            for item in stream(spoken, voice=voice, speed=speed, lang=language):
                samples, rate = item[0], item[1]
                pcm = float_array_to_pcm16(samples)
                if not pcm:
                    continue
                yielded = True
                yield pcm, int(rate)
        except Exception:
            logger.exception("kokoro_stream_failed")
            if yielded:
                return
        else:
            if yielded:
                return
    create = getattr(engine, "create", None)
    if not callable(create):
        return
    samples, rate = create(spoken, voice=voice, speed=speed, lang=language)
    pcm = float_array_to_pcm16(samples)
    if pcm:
        yield pcm, int(rate)


def open_kokoro(model_path: Path, voices_path: Path, cpu_threads: int = 4):
    """Load Kokoro on CUDA when the runtime has it, and cap CPU threads otherwise."""
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    providers, threads = onnx_session_plan(onnx_providers(), cpu_threads)
    original = ort.InferenceSession

    def session(model: object, sess_options: object = None, providers: object = None, *args: object, **kwargs: object):
        del args
        options = sess_options if sess_options is not None else ort.SessionOptions()
        intra = getattr(options, "intra_op_num_threads", None)
        if intra == 0 or intra is None:
            options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        chosen = list(providers) if isinstance(providers, (list, tuple)) and providers else list(onnx_providers())
        return original(model, options, providers=chosen, **kwargs)

    ort.InferenceSession = session  # type: ignore[method-assign]
    try:
        engine = Kokoro(str(model_path), str(voices_path))
    finally:
        ort.InferenceSession = original  # type: ignore[method-assign]
    return engine


class KokoroSynthesizer:
    """Speak text with the local Kokoro model. Returns 16-bit mono PCM and its sample rate."""

    def __init__(self, model_path: Path, voices_path: Path, voice: str, speed: float = 1.08, cpu_threads: int = 4) -> None:
        self._engine = open_kokoro(model_path, voices_path, cpu_threads)
        if voice not in self._engine.get_voices():
            raise ValueError(f"Unsupported Kokoro voice: {voice}")
        self._voice = voice
        self._speed = speed
        self._language = kokoro_language(voice)
        session = getattr(self._engine, "sess", None)
        names = session.get_providers() if session is not None and hasattr(session, "get_providers") else onnx_providers()
        self.provider = names[0] if names else "CPUExecutionProvider"

    def synthesize(self, text: str) -> tuple[bytes, int]:
        spoken = " ".join(text.split())
        if not spoken:
            return b"", _KOKORO_RATE
        samples, rate = self._engine.create(spoken, voice=self._voice, speed=self._speed, lang=self._language)
        return float_array_to_pcm16(samples), int(rate)

    def iter_pcm(self, text: str) -> Iterator[tuple[bytes, int]]:
        yield from synthesize_pieces(
            self._engine,
            text,
            voice=self._voice,
            speed=self._speed,
            language=self._language,
        )


class PiperSynthesizer:
    """Speak text with a local Piper voice. Returns 16-bit mono PCM and its sample rate."""

    def __init__(self, model_path: Path) -> None:
        from piper import PiperVoice

        self._voice = PiperVoice.load(str(model_path))

    def synthesize(self, text: str) -> tuple[bytes, int]:
        spoken = " ".join(text.split())
        if not spoken:
            return b"", 22050
        from piper.config import SynthesisConfig

        question = spoken.endswith("?")
        config = SynthesisConfig(
            length_scale=1.22 if question else 1.4,
            noise_scale=0.32,
            noise_w_scale=0.4,
        )
        synthesize = getattr(self._voice, "synthesize", None)
        if synthesize is not None:
            audio, rate = pcm_from_chunks(list(synthesize(spoken, syn_config=config)))
            if audio:
                return audio, rate
        import io
        import wave

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            self._voice.synthesize_wav(spoken, wav_file)
        buffer.seek(0)
        with wave.open(buffer, "rb") as wav_file:
            return wav_file.readframes(wav_file.getnframes()), wav_file.getframerate()


def trim_trailing_silence(pcm: bytes, sample_rate: int = 16000, threshold: float = 0.02, pad_ms: int = 300) -> bytes:
    """Drop the quiet tail so transcription does not decode a long pause."""
    samples = len(pcm) // 2
    if samples == 0 or sample_rate <= 0:
        return pcm
    frame = max(1, sample_rate // 50)
    last_loud = 0
    for offset in range(0, samples, frame):
        end = min(samples, offset + frame)
        if pcm16_rms(pcm[offset * 2 : end * 2]) >= threshold:
            last_loud = end
    if last_loud == 0:
        return pcm[: min(samples, frame) * 2]
    keep = min(samples, last_loud + sample_rate * pad_ms // 1000)
    return pcm[: keep * 2]


class WhisperRecognizer:
    """Transcribe 16-bit PCM with a local Whisper model."""

    def __init__(self, model_name: str, device: str, download_root: str, cpu_threads: int = 4) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_name, download_root=download_root, **whisper_model_kwargs(device, cpu_threads))
        self.prompt = ""

    def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        import numpy as np

        samples = pcm16_to_float(trim_trailing_silence(pcm, sample_rate))
        if sample_rate != 16000:
            samples = resample_linear(samples, sample_rate, 16000)
        segments, _info = self._model.transcribe(
            np.asarray(samples, dtype=np.float32),
            **whisper_transcribe_kwargs(self.prompt),
        )
        return join_segment_text(segments)


_HINT_WORDS = (
    "Python",
    "FastAPI",
    "PostgreSQL",
    "Postgres",
    "Docker",
    "Redis",
    "React",
    "Dhaka",
    "Gulshan",
)
_PROPER = re.compile(r"\b[A-Z][A-Za-z0-9+#.]{2,}(?:[ \t]+[A-Z][A-Za-z0-9+#.]{2,}){0,2}\b")


def speech_hints(questions: list[str], profile: str, *, limit: int = 40) -> list[str]:
    """Words the transcriber should prefer: checklist tools and names written on the CV."""
    blob = "\n".join(questions) + "\n" + profile
    folded = blob.casefold()
    found: list[str] = []
    for word in _HINT_WORDS:
        if word.casefold() in folded:
            found.append(word)
    for match in _PROPER.finditer(profile):
        phrase = " ".join(match.group(0).split())
        if phrase.casefold() in {item.casefold() for item in found}:
            continue
        found.append(phrase)
        if len(found) >= limit:
            break
    return found[:limit]


def speech_prompt(questions: list[str], profile: str) -> str:
    hints = speech_hints(questions, profile)
    if not hints:
        return ""
    return "Terms: " + ", ".join(hints)
