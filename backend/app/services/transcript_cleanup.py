"""Scoring view of a transcript. The stored lines stay as they were spoken."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

_DISFLUENCY = re.compile(r"^(?:u+h+m*|u+m+h*|u+h+|u+m+|e+r+m*|e+r+|a+h+|h+m+|m{2,}|eh+)$")
_LEADING_HEDGES = frozenset({"so", "well", "like", "okay", "ok"})
_RECRUITER_ASIDES = frozenset(
    {
        "okay",
        "ok",
        "sure",
        "right",
        "great",
        "thanks",
        "thank you",
        "take your time",
        "no problem",
        "go ahead",
        "no rush",
        "whenever you're ready",
        "mm hmm",
        "mm-hmm",
        "mhm",
        "yeah",
        "yes",
        "uh huh",
        "uh-huh",
        "alright",
        "all right",
        "got it",
        "i see",
        "interesting",
    }
)


@dataclass(frozen=True)
class PairedSpeech:
    question: str
    answer: str
    start: float
    end: float


def core_token(token: str) -> str:
    return token.strip(".,!?;:\"'").lower()


def normalized(text: str) -> str:
    words = [core_token(token) for token in text.split()]
    return " ".join(word for word in words if word)


def is_disfluency(word: str) -> bool:
    return bool(_DISFLUENCY.fullmatch(core_token(word)))


def is_disfluency_only(text: str) -> bool:
    words = [core_token(token) for token in text.split() if core_token(token)]
    return bool(words) and all(is_disfluency(word) for word in words)


def without_disfluency(text: str) -> str:
    kept = [token for token in text.split() if not is_disfluency(token)]
    return " ".join(kept).strip()


def substantive(text: str) -> str:
    """Drop uhm/uhh and a leading so/well so filler is not scored as the answer."""
    kept = without_disfluency(text).split()
    start = 0
    while start < len(kept) - 1 and core_token(kept[start]) in _LEADING_HEDGES:
        start += 1
    return " ".join(kept[start:]).strip()


def recruiter_aside(text: str) -> bool:
    return normalized(text) in _RECRUITER_ASIDES


def same_line(left: str, right: str) -> bool:
    spoken = normalized(left)
    return bool(spoken) and spoken == normalized(right)


def pair_speech(
    turns: Sequence[tuple[str, str, float, float]],
    *,
    unasked: str = "",
) -> list[PairedSpeech]:
    """Pair each question with the answer that follows, after filler and asides are ignored."""
    pairs: list[PairedSpeech] = []
    question: str | None = None
    question_start: float | None = None
    question_end: float | None = None
    answer_parts: list[str] = []
    answer_start: float | None = None
    answer_end: float | None = None
    last_prompt = ""

    def flush() -> None:
        nonlocal question, question_start, question_end, answer_parts, answer_start, answer_end
        if question is None and not answer_parts:
            return
        asked = question if question is not None else unasked
        spoken = " ".join(answer_parts).strip()
        start = answer_start if answer_start is not None else question_start or 0.0
        end = answer_end if answer_end is not None else question_end or start
        pairs.append(PairedSpeech(asked, spoken, start, end))
        question = None
        question_start = None
        question_end = None
        answer_parts = []
        answer_start = None
        answer_end = None

    for speaker, text, start, end in turns:
        text = text.strip()
        if not text:
            continue
        if speaker == "recruiter":
            if recruiter_aside(text):
                continue
            if answer_parts:
                flush()
            last_prompt = text
            if question:
                question = f"{question} {text}"
                question_end = end
                continue
            question = text
            question_start = start
            question_end = end
            continue
        heard = without_disfluency(text)
        if not heard:
            continue
        if same_line(heard, last_prompt) or (question is not None and same_line(heard, question)):
            continue
        spoken = substantive(heard)
        if not spoken:
            continue
        if not answer_parts:
            answer_start = start
        answer_parts.append(spoken)
        answer_end = end
    flush()
    return pairs
