import array
import struct
import sys
from collections.abc import Iterable
from pathlib import Path

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
        self._chunks: list[bytes] = []
        self._samples = 0

    @property
    def armed(self) -> bool:
        return self._armed

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
        return audio


class BargeMeter:
    """Notice when the candidate talks over the interviewer for long enough to interrupt."""

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.08, hold_ms: int = 250) -> None:
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
            length_scale=1.08 if question else 1.24,
            noise_scale=0.4,
            noise_w_scale=0.48,
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

    def __init__(self, model_name: str, device: str, download_root: str) -> None:
        from faster_whisper import WhisperModel

        compute = "int8" if device == "cpu" else "float16"
        self._model = WhisperModel(model_name, device=device, compute_type=compute, download_root=download_root)

    def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        import numpy as np

        samples = pcm16_to_float(trim_trailing_silence(pcm, sample_rate))
        if sample_rate != 16000:
            samples = resample_linear(samples, sample_rate, 16000)
        segments, _info = self._model.transcribe(
            np.asarray(samples, dtype=np.float32),
            language="en",
            vad_filter=True,
            beam_size=1,
            best_of=1,
            condition_on_previous_text=False,
        )
        return join_segment_text(segments)
