import httpx
import pytest

from app.services.cloud_speech import (
    GroqRecognizer,
    GroqSynthesizer,
    pace_pcm16,
    pcm16_wav,
    speech_chunks,
    wav_to_pcm16,
)


def test_a_long_line_is_split_where_the_api_allows() -> None:
    pieces = speech_chunks("word " * 80)
    assert pieces
    assert all(len(piece) <= 180 for piece in pieces)
    assert " ".join(pieces) == ("word " * 80).strip()


def test_pcm_round_trips_through_a_wav() -> None:
    pcm = (b"\x01\x00" * 8)
    audio, rate = wav_to_pcm16(pcm16_wav(pcm, 16000))
    assert rate == 16000
    assert audio == pcm


def test_groq_hears_the_transcript() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/audio/transcriptions")
        body = request.read()
        assert b"whisper-large-v3-turbo" in body
        assert b"Practice guest" in body
        return httpx.Response(200, json={"text": "  I led the migration.  "})

    heard = GroqRecognizer(
        "test-key",
        "whisper-large-v3-turbo",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    heard.prompt = "Practice guest"
    assert heard.transcribe(b"\x01\x00" * 160, 16000) == "I led the migration."


def test_groq_speaks_a_line_longer_than_one_request() -> None:
    calls: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.read())
        return httpx.Response(200, content=pcm16_wav(b"\x02\x00" * 4, 24000))

    voice = GroqSynthesizer(
        "test-key",
        "canopylabs/orpheus-v1-english",
        "autumn",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    pcm, rate = voice.synthesize(("hello " * 50).strip())
    assert rate == 24000
    assert len(calls) >= 2
    assert pcm == b"\x02\x00" * 4 * len(calls)


def test_the_same_voice_is_played_faster() -> None:
    spoken = pace_pcm16(b"\x02\x00" * 24000, 24000, speed=1.5)
    assert spoken
    assert len(spoken) < 24000 * 2 * 0.8


def test_groq_speech_failure_names_the_status() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid key")

    voice = GroqSynthesizer(
        "test-key",
        "canopylabs/orpheus-v1-english",
        "autumn",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError, match="status=401"):
        voice.synthesize("Hello.")
