import logging
import math
import os
import tempfile

logger = logging.getLogger(__name__)

_MAX_CHUNK_BYTES = 2_000_000


class AudioTranscriptionError(Exception):
    """A chunk could not be transcribed. The call itself continues."""


class FasterWhisperTranscriber:
    def __init__(self, *, model_name: str, device: str, compute_type: str) -> None:
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._model: object | None = None

    def transcribe(self, data: bytes) -> tuple[str, float]:
        if len(data) < 64 or len(data) > _MAX_CHUNK_BYTES:
            return "", 0.0
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise AudioTranscriptionError("Speech recognition is not available.") from exc
        if self._model is None:
            self._model = WhisperModel(self._model_name, device=self._device, compute_type=self._compute_type)
        descriptor, path = tempfile.mkstemp(suffix=".webm")
        try:
            os.write(descriptor, data)
        finally:
            os.close(descriptor)
        try:
            segments, _info = self._model.transcribe(path, vad_filter=True)  # type: ignore[attr-defined]
            parts: list[str] = []
            confidence_total = 0.0
            confidence_count = 0
            for segment in segments:
                text = segment.text.strip()
                if text:
                    parts.append(text)
                confidence_total += _confidence(segment.avg_logprob)
                confidence_count += 1
            confidence = confidence_total / confidence_count if confidence_count else 0.0
            return " ".join(parts).strip(), confidence
        except AudioTranscriptionError:
            raise
        except Exception as exc:
            logger.warning("whisper_chunk_failed error_type=%s", type(exc).__name__)
            raise AudioTranscriptionError("This audio chunk could not be transcribed.") from exc
        finally:
            try:
                os.unlink(path)
            except OSError:
                logger.warning("whisper_temp_cleanup_failed")


def _confidence(avg_logprob: float | None) -> float:
    if avg_logprob is None:
        return 0.0
    try:
        value = math.exp(float(avg_logprob))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return max(0.0, min(1.0, value))


_transcriber: FasterWhisperTranscriber | None = None


def get_transcriber() -> FasterWhisperTranscriber:
    global _transcriber
    if _transcriber is None:
        from app.core.config import get_settings

        settings = get_settings()
        _transcriber = FasterWhisperTranscriber(
            model_name=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    return _transcriber
