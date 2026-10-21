import logging
import re
from dataclasses import dataclass

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import JobGraphError, parse_json_object

GENERAL_QUESTIONS = (
    "Tell me about a recent project you are proud of.",
    "What part of that work was hardest, and how did you handle it?",
    "What would you want this role to use from that experience?",
)
_ANSWER_CAP = 8
_SAY_LIMIT = 500
logger = logging.getLogger(__name__)
_SYSTEM = (
    "You are conducting a live job interview. You speak aloud, so say is one or two short sentences. "
    "Return only a JSON object with keys say (string), answered (boolean), covered (list of checklist items), "
    "done (boolean), and quiz (boolean). "
    "The checklist is a private scoring rubric. Never read it aloud and never say 'the candidate'. "
    "Look at what the candidate just said before you choose the next checklist item. "
    "If it answers the open checklist question, set answered true. "
    "Restate the answer in the second person. Do not repeat their sentence. "
    "Never say I, I've, I'm, or my about their experience. Those words would mean you did the work. "
    "If they say 'yes I have 10 years of experience', say 'So you have 10 years of experience.' "
    "Then ask one natural question about the next uncovered checklist item, and put the open item in covered. "
    "If it is a question, a request, or about the camera, microphone, or anything else, set answered false and leave covered empty. "
    "Answer that in your own words. If you cannot know, say so. Do not repeat their question back. "
    "Then ask the same open checklist question again. "
    "Do not start a new checklist item on that turn. "
    "If they have not spoken yet, set answered false and ask the first checklist item in your own words. "
    "Do not invent requirements. covered may only contain exact checklist items. "
    "When the checklist is covered, or the candidate has answered enough, set done and quiz to true "
    "and say a short goodbye that mentions a skill quiz."
)
_QUESTION_LEADS = (
    "what ",
    "why ",
    "how ",
    "when ",
    "where ",
    "who ",
    "which ",
    "can you ",
    "could you ",
    "would you ",
    "will you ",
    "do you ",
    "did you ",
    "is ",
    "are ",
    "isn't ",
    "aren't ",
    "is there ",
    "are there ",
    "can i ",
    "could i ",
    "have you ",
    "don't you ",
    "can't you ",
)
_CALL_CHECKS = ("my camera", "my video", "my mic", "my microphone", "hear me", "see me", "you hear", "you see")
_FILLERS = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "right",
    "correct",
    "absolutely",
    "no",
    "nope",
    "nah",
    "well",
    "so",
    "um",
    "uh",
    "okay",
    "ok",
    "and",
}
_GREETINGS = {"hi", "hello", "hey", "thanks", "thank you"}
_RUBRIC_LEADS = (
    ("does the candidate ", "Do you "),
    ("can the candidate ", "Can you "),
    ("has the candidate ", "Have you "),
    ("is the candidate able to ", "Can you "),
    ("is the candidate ", "Are you "),
    ("will the candidate ", "Will you "),
    ("did the candidate ", "Did you "),
)


@dataclass(frozen=True)
class Agenda:
    questions: tuple[str, ...]
    covered: tuple[str, ...] = ()
    asked: tuple[str, ...] = ()
    answers: int = 0


@dataclass(frozen=True)
class Utterance:
    say: str
    covered: tuple[str, ...]
    finished: bool
    offer_quiz: bool
    answered: bool = False
    asks: str = ""


def opening_line(company: str, job_title: str, candidate_name: str, first_question: str = "") -> str:
    """The first thing the interviewer says. It tells the candidate this is an AI."""
    name = " ".join(candidate_name.split()) or "there"
    role = " ".join(job_title.split()) or "this"
    company_name = " ".join(company.split()) or "the company"
    intro = (
        f"Hello {name}. I am the AI interviewer for the {role} role at {company_name}. "
        "I will ask a few questions about your experience, and then there is a short skill quiz."
    )
    question = " ".join(first_question.split())
    if not question:
        return intro
    return f"{intro} {question}"


def first_question(questions: tuple[str, ...]) -> str:
    if questions:
        return questions[0]
    return GENERAL_QUESTIONS[0]


def spoken_sentences(text: str) -> tuple[str, ...]:
    """Split a spoken line so the first sentence can play before the rest is ready."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return ()
    sentences: list[str] = []
    start = 0
    for index, char in enumerate(cleaned):
        if char in ".!?" and index - start >= 20:
            sentences.append(cleaned[start : index + 1].strip())
            start = index + 1
    tail = cleaned[start:].strip()
    if tail:
        sentences.append(tail)
    return tuple(sentences) or (cleaned,)


def spoken_question(rubric: str) -> str:
    """Turn a third-person scoring line into a question addressed to the candidate."""
    text = " ".join(rubric.split())
    if not text:
        return GENERAL_QUESTIONS[0]
    lowered = text.lower()
    for prefix, lead in _RUBRIC_LEADS:
        if lowered.startswith(prefix):
            text = lead + text[len(prefix) :]
            lowered = text.lower()
            break
    marker = "the candidate"
    found = lowered.find(marker)
    if found >= 0:
        text = text[:found] + "you" + text[found + len(marker) :]
    if text[-1] not in ".?!":
        text += "?"
    elif text.endswith("."):
        text = text[:-1] + "?"
    return text[:1].upper() + text[1:]


def answer_limit(agenda: Agenda) -> int:
    if not agenda.questions:
        return len(GENERAL_QUESTIONS)
    return min(_ANSWER_CAP, len(agenda.questions))


def note_answer(agenda: Agenda) -> Agenda:
    """Count a real answer and treat the open checklist item as discussed."""
    covered = agenda.covered
    open_item = _open_item(agenda)
    if open_item and open_item not in covered:
        covered = (*covered, open_item)
    return Agenda(
        questions=agenda.questions,
        covered=covered,
        asked=agenda.asked,
        answers=agenda.answers + 1,
    )


def candidate_asked(text: str) -> bool:
    """True when the candidate asked something instead of answering."""
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return False
    if cleaned.endswith("?"):
        return True
    lowered = cleaned.lower().strip(".! ")
    if lowered.startswith(_QUESTION_LEADS):
        return True
    return any(phrase in lowered for phrase in _CALL_CHECKS)


def turn_is_answer(text: str) -> bool:
    """True when this turn should move the checklist forward."""
    cleaned = " ".join(text.split()).strip(".! ")
    if not cleaned or cleaned.lower() in _GREETINGS:
        return False
    return not candidate_asked(text)


def echoes_prompt(heard: str, spoken: str) -> bool:
    """True when the microphone mostly played the interviewer's own last line back."""
    heard_words = heard.lower().split()
    spoken_words = set(spoken.lower().split())
    if len(heard_words) < 6 or not spoken_words:
        return False
    overlap = sum(1 for word in heard_words if word in spoken_words)
    return overlap / len(heard_words) >= 0.75


async def plan_reply(
    llm: FallbackLLMManager,
    agenda: Agenda,
    *,
    company: str,
    job_title: str,
    profile: str,
    transcript: str,
    heard: str,
) -> tuple[Utterance, Agenda]:
    """Answer what was just said, then continue the checklist only after a real answer."""
    if agenda.answers >= answer_limit(agenda) or not _remaining(agenda):
        utterance = _closing()
        return utterance, _apply(agenda, utterance)
    prompt = _prompt(agenda, company=company, job_title=job_title, profile=profile, transcript=transcript, heard=heard)
    try:
        response = await llm.complete_live(prompt, system=_SYSTEM)
        payload = parse_json_object(response.content)
        utterance = utterance_from_model(agenda, payload)
        answered = _model_answered(payload, heard)
    except (JobGraphError, Exception) as exc:
        logger.warning("interviewer_plan_failed error_type=%s", type(exc).__name__)
        utterance = fallback_utterance(agenda, heard=heard)
        answered = turn_is_answer(heard)
    if not utterance.say or _reads_rubric(utterance.say):
        utterance = fallback_utterance(agenda, heard=heard)
        answered = turn_is_answer(heard) and bool(utterance.say) and not candidate_asked(heard)
    utterance = _shape_reply(agenda, utterance, heard=heard, answered=answered and turn_is_answer(heard))
    return utterance, _apply(agenda, utterance)


def utterance_from_model(agenda: Agenda, payload: dict[str, object]) -> Utterance:
    allowed = set(_source(agenda))
    covered = tuple(item for item in _strings(payload.get("covered")) if item in allowed)
    say = spoken_limit(_text(payload.get("say")))
    ready_to_finish = agenda.answers >= answer_limit(agenda) or not _remaining(agenda)
    if payload.get("done") is True and not ready_to_finish:
        return Utterance(say=say, covered=covered, finished=False, offer_quiz=False)
    if payload.get("done") is True or agenda.answers >= answer_limit(agenda):
        return Utterance(say=say or _closing().say, covered=covered or agenda.covered, finished=True, offer_quiz=True)
    return Utterance(say=say, covered=covered, finished=False, offer_quiz=payload.get("quiz") is True)


def fallback_utterance(agenda: Agenda, *, heard: str = "") -> Utterance:
    """A local line when the model misses. A question does not skip to the next rubric item."""
    if agenda.answers >= answer_limit(agenda) or not _remaining(agenda):
        return _closing()
    if candidate_asked(heard):
        current = _open_or_next(agenda)
        return Utterance(
            say=f"{_aside_reply(heard)} {spoken_question(current)}".strip(),
            covered=(),
            finished=False,
            offer_quiz=False,
            answered=False,
            asks=current if current not in agenda.asked else "",
        )
    if not turn_is_answer(heard):
        current = _open_or_next(agenda)
        return Utterance(
            say=spoken_question(current),
            covered=(),
            finished=False,
            offer_quiz=False,
            answered=False,
            asks=current if current not in agenda.asked else "",
        )
    nxt = _after_answer(agenda)
    if not nxt:
        return _closing()
    reflected = f"{mirror(heard)} {spoken_question(nxt)}".strip()
    return Utterance(say=reflected, covered=(), finished=False, offer_quiz=False, answered=True, asks=nxt)


def spoken_limit(text: str, max_chars: int = _SAY_LIMIT) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars]
    stop = max(cut.rfind("."), cut.rfind("?"), cut.rfind("!"))
    if stop > 40:
        return cut[: stop + 1]
    return cut


def _closing() -> Utterance:
    return Utterance(
        say="Thank you. That covers my questions. I am opening a short skill quiz for you now.",
        covered=(),
        finished=True,
        offer_quiz=True,
    )


def _apply(agenda: Agenda, utterance: Utterance) -> Agenda:
    covered = list(agenda.covered)
    asked = list(agenda.asked)
    answers = agenda.answers
    if utterance.answered:
        open_item = _open_item(agenda)
        if open_item and open_item not in covered:
            covered.append(open_item)
        for item in utterance.covered:
            if item in _source(agenda) and item not in covered:
                covered.append(item)
        answers += 1
    if utterance.asks and utterance.asks in _source(agenda) and utterance.asks not in asked:
        asked.append(utterance.asks)
    return Agenda(
        questions=agenda.questions,
        covered=tuple(covered),
        asked=tuple(asked),
        answers=answers,
    )


def _remaining(agenda: Agenda) -> tuple[str, ...]:
    return tuple(item for item in _source(agenda) if item not in agenda.covered and item not in agenda.asked)


def _source(agenda: Agenda) -> tuple[str, ...]:
    return agenda.questions or GENERAL_QUESTIONS


_FIRST_PERSON = re.compile(r"\b(i|i['’]m|i['’]ve|i['’]ll|i['’]d|my)\b", re.IGNORECASE)
_PRONOUNS = (
    (re.compile(r"\bi['’]m\b", re.IGNORECASE), "you are"),
    (re.compile(r"\bi am\b", re.IGNORECASE), "you are"),
    (re.compile(r"\bi['’]ve\b", re.IGNORECASE), "you have"),
    (re.compile(r"\bi have\b", re.IGNORECASE), "you have"),
    (re.compile(r"\bi['’]ll\b", re.IGNORECASE), "you will"),
    (re.compile(r"\bi will\b", re.IGNORECASE), "you will"),
    (re.compile(r"\bi['’]d\b", re.IGNORECASE), "you would"),
    (re.compile(r"\bi would\b", re.IGNORECASE), "you would"),
    (re.compile(r"\bmy\b", re.IGNORECASE), "your"),
    (re.compile(r"\bme\b", re.IGNORECASE), "you"),
    (re.compile(r"\bi\b", re.IGNORECASE), "you"),
)


def mirror(heard: str) -> str:
    """Say their whole answer back in the second person."""
    text = " ".join(heard.split()).strip(" .!?")
    if len(text) > 120:
        text = text[:120].rsplit(" ", 1)[0]
    words = text.split()
    index = 0
    while index < len(words) and words[index].lower().strip(",") in _FILLERS:
        index += 1
    kept = words[index:] or words
    body = _to_second_person(" ".join(kept))
    if body and not body.endswith("."):
        body += "."
    return f"So {body}" if body else ""


def _to_second_person(text: str) -> str:
    body = text
    for pattern, replacement in _PRONOUNS:
        body = pattern.sub(replacement, body)
    return body


def _slips_into_first_person(say: str) -> bool:
    """True when the reply still talks as if it did the candidate's work."""
    return _FIRST_PERSON.search(say) is not None


def _drop_ok_so(say: str) -> str:
    cleaned = say.strip()
    lowered = cleaned.lower()
    for lead in ("okay, so ", "ok, so ", "okay so ", "ok so "):
        if lowered.startswith(lead):
            cleaned = cleaned[len(lead) :].strip()
            break
    if not cleaned:
        return say.strip()
    return cleaned[:1].upper() + cleaned[1:]


def copies_candidate(say: str, heard: str) -> bool:
    """True when the spoken line is mostly the candidate's own words."""
    heard_norm = " ".join(heard.lower().split()).strip(" .!?")
    say_norm = " ".join(say.lower().split())
    if len(heard_norm) >= 12 and heard_norm in say_norm:
        return True
    heard_words = [word.strip(".,?!") for word in heard_norm.split() if len(word.strip(".,?!")) > 2]
    if len(heard_words) < 4:
        return False
    say_words = set(say_norm.split())
    overlap = sum(1 for word in heard_words if word in say_words)
    return overlap / len(heard_words) >= 0.75


def _aside_reply(heard: str) -> str:
    """A short answer for a turn that is not an answer to the checklist."""
    lowered = heard.lower()
    if any(word in lowered for word in ("camera", "video", "mic", "microphone", "audio", "hear", "sound")):
        return "I can't check your camera or microphone from here. If you can see and hear me, we can continue."
    return "I don't have that in front of me."


def _echoes_answer(say: str, heard: str) -> bool:
    heard_words = {word for word in heard.lower().split() if len(word) > 3}
    if not heard_words:
        return False
    say_words = set(say.lower().split())
    return sum(1 for word in heard_words if word in say_words) >= 2


def _open_item(agenda: Agenda) -> str:
    for item in reversed(agenda.asked):
        if item not in agenda.covered:
            return item
    return ""


def _open_or_next(agenda: Agenda) -> str:
    current = _open_item(agenda)
    if current:
        return current
    remaining = _remaining(agenda)
    return remaining[0] if remaining else ""


def _after_answer(agenda: Agenda) -> str:
    current = _open_item(agenda)
    for item in _source(agenda):
        if item == current or item in agenda.covered or item in agenda.asked:
            continue
        return item
    return ""


def _model_answered(payload: dict[str, object], heard: str) -> bool:
    if not turn_is_answer(heard):
        return False
    if "answered" in payload:
        return payload.get("answered") is True
    return True


def _shape_reply(agenda: Agenda, utterance: Utterance, *, heard: str, answered: bool) -> Utterance:
    if utterance.finished:
        return utterance
    if not answered:
        current = _open_or_next(agenda)
        question = spoken_question(current) if current else ""
        say = utterance.say or question
        if _reads_rubric(say) or (candidate_asked(heard) and copies_candidate(say, heard)):
            say = _aside_reply(heard) if candidate_asked(heard) else question
        if current and question.lower() not in say.lower() and heard.strip():
            say = f"{say.rstrip()} {question}"
        asks = current if current not in agenda.asked else ""
        return Utterance(say=say, covered=(), finished=False, offer_quiz=False, answered=False, asks=asks)
    nxt = _after_answer(agenda)
    if not nxt:
        return _closing()
    question = spoken_question(nxt)
    say = utterance.say or question
    if _reads_rubric(say) or copies_candidate(say, heard) or _slips_into_first_person(say):
        say = f"{mirror(heard)} {question}".strip()
    elif heard.strip() and not say.lower().startswith("so ") and not _echoes_answer(say, heard):
        say = f"{mirror(heard)} {_drop_ok_so(say)}".strip()
    else:
        say = _drop_ok_so(say)
    return Utterance(say=say, covered=(), finished=False, offer_quiz=False, answered=True, asks=nxt)


def _prompt(
    agenda: Agenda,
    *,
    company: str,
    job_title: str,
    profile: str,
    transcript: str,
    heard: str,
) -> str:
    checklist = "\n".join(f"- {item}" for item in _source(agenda))
    asked = "\n".join(f"- {item}" for item in agenda.asked) or "- (none yet)"
    covered = "\n".join(f"- {item}" for item in agenda.covered) or "- (none yet)"
    open_item = _open_item(agenda) or "(none yet — ask the first checklist item)"
    profile_text = profile.strip() or "No CV is stored for this person."
    history = transcript.strip() or "(no speech yet)"
    return (
        f"Company: {company}\nRole: {job_title}\n"
        f"CV profile:\n{profile_text}\n\n"
        f"Checklist:\n{checklist}\n\n"
        f"Already asked:\n{asked}\n\n"
        f"Already covered:\n{covered}\n\n"
        f"Open checklist question:\n{open_item}\n\n"
        f"Transcript:\n{history}\n\n"
        f"Candidate just said:\n{heard.strip()}"
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _reads_rubric(text: str) -> bool:
    return "the candidate" in text.lower()
