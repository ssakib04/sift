"""Hearing and speech through Groq, so the interview does not run Whisper or Kokoro locally."""

import array
import struct
import wave
from io import BytesIO

import httpx

_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_TTS_URL = "https://api.groq.com/openai/v1/audio/speech"
_CHUNK_CHARS = 180
_TIMEOUT = 30.0
_SPEECH_SPEED = 1.5


def speech_chunks(text: str, limit: int = _CHUNK_CHARS) -> list[str]:
    """Split a line into pieces the speech API will accept."""
    spoken = " ".join(text.split())
    if not spoken:
        return []
    parts: list[str] = []
    rest = spoken
    while rest:
        if len(rest) <= limit:
            parts.append(rest)
            break
        cut = rest.rfind(" ", 0, limit + 1)
        if cut < 40:
            cut = limit
        piece = rest[:cut].strip()
        if piece:
            parts.append(piece)
        rest = rest[cut:].strip()
    return parts


def pcm16_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap 16-bit mono PCM in a wav the transcription API can read."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def wav_to_pcm16(blob: bytes) -> tuple[bytes, int]:
    """Read a 16-bit mono wav into PCM and its sample rate."""
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise ValueError("speech response was not a wav")
    rate = 24000
    channels = 1
    width = 2
    data = b""
    offset = 12
    while offset + 8 <= len(blob):
        kind = blob[offset : offset + 4]
        size = struct.unpack_from("<I", blob, offset + 4)[0]
        start = offset + 8
        chunk = blob[start : start + size]
        if kind == b"fmt " and len(chunk) >= 16:
            audio_format, channels, rate = struct.unpack_from("<HHI", chunk, 0)
            width = struct.unpack_from("<H", chunk, 14)[0]
            if audio_format != 1 or width != 16:
                raise ValueError("speech response was not 16-bit PCM")
        elif kind == b"data":
            data = chunk
        offset = start + size + (size % 2)
    if not data:
        raise ValueError("speech response had no audio")
    if channels == 2:
        samples = memoryview(data).cast("h")
        data = struct.pack("<" + "h" * (len(samples) // 2), *samples[::2])
    elif channels != 1:
        raise ValueError("speech response was not mono or stereo")
    return data, rate


def pace_pcm16(pcm: bytes, sample_rate: int, speed: float = _SPEECH_SPEED) -> bytes:
    """Shorten the audio so the same voice speaks faster.

    Orpheus ignores a speed field, so the pace is applied to the waveform.
    Overlapping frames keep the pitch of the original voice.
    """
    if speed <= 1.01 or sample_rate <= 0 or len(pcm) < 4:
        return pcm
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    frame = max(2, int(sample_rate * 0.02))
    if len(samples) < frame * 2:
        return pcm
    synthesis_hop = max(1, frame // 2)
    analysis_hop = max(synthesis_hop + 1, int(synthesis_hop * speed))
    overlap = frame - synthesis_hop
    output = array.array("h")
    position = 0
    while position + frame <= len(samples):
        piece = samples[position : position + frame]
        if not output:
            output.extend(piece)
        else:
            base = len(output) - overlap
            for index in range(overlap):
                fade = index / overlap
                mixed = int(output[base + index] * (1.0 - fade) + piece[index] * fade)
                output[base + index] = max(-32768, min(32767, mixed))
            output.extend(piece[overlap:])
        position += analysis_hop
    if not output:
        return pcm
    return output.tobytes()


class GroqRecognizer:
    """Transcribe 16-bit PCM with Groq Whisper."""

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self.prompt = ""
        self._key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        if not pcm:
            return ""
        fields = {
            "model": self._model,
            "language": "en",
            "response_format": "json",
            "temperature": "0",
        }
        if self.prompt.strip():
            fields["prompt"] = self.prompt.strip()[:800]
        response = self._client.post(
            _STT_URL,
            headers={"Authorization": f"Bearer {self._key}"},
            data=fields,
            files={"file": ("audio.wav", pcm16_wav(pcm, sample_rate), "audio/wav")},
        )
        _raise_for_status(response)
        text = response.json().get("text", "")
        return " ".join(str(text).split())


class GroqSynthesizer:
    """Speak with Groq Orpheus. Returns 16-bit mono PCM and its sample rate."""

    def __init__(self, api_key: str, model: str, voice: str, client: httpx.Client | None = None) -> None:
        self._key = api_key
        self._model = model
        self._voice = voice
        self._client = client or httpx.Client(timeout=_TIMEOUT)
        self.provider = "groq"

    def synthesize(self, text: str) -> tuple[bytes, int]:
        pieces = list(self.iter_pcm(text))
        if not pieces:
            return b"", 24000
        rate = pieces[0][1]
        return b"".join(pcm for pcm, _piece_rate in pieces), rate

    def iter_pcm(self, text: str):
        for piece in speech_chunks(text):
            response = self._client.post(
                _TTS_URL,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={
                    "model": self._model,
                    "voice": self._voice,
                    "input": piece,
                    "response_format": "wav",
                },
            )
            _raise_for_status(response)
            pcm, rate = wav_to_pcm16(response.content)
            pcm = pace_pcm16(pcm, rate)
            if pcm:
                yield pcm, rate


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    detail = " ".join(response.text.split())[:180]
    raise RuntimeError(f"groq speech failed status={response.status_code} {detail}")
