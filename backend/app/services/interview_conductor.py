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
_ACKS = ("Okay.", "Right.", "Got it.")
_NUDGES = (
    "Take your time. I am still here.",
    "Whenever you are ready.",
)
HOLD_LINE = "uh huh."
QUIZ_LINE = "I am opening the short skill quiz now."
logger = logging.getLogger(__name__)
_SYSTEM = (
    "You are conducting a live video interview. You can see and hear the candidate. "
    "You speak aloud, so say is one or two short sentences. "
    "Never say you are a text interface, a chatbot, or an AI that cannot see or hear. "
    "If they ask whether you can see or hear them, say yes in a few words. "
    "Do not describe their face, clothes, or room. "
    "Return only a JSON object with keys say (string), answered (boolean), covered (list of checklist items), "
    "done (boolean), and quiz (boolean). "
    "The checklist is a private scoring rubric. Never read it aloud, never say 'the candidate', and never quote it. "
    "Ask one natural question a person would ask. Do not turn a rubric line into 'Do you demonstrate'. "
    "Sound calm. Do not restate their sentence and do not start with 'So you'. "
    "Do not repeat names, companies, or other proper nouns from their last sentence. "
    "If you mention their background, use the CV's wording, and do that only when it helps this question. "
    "If their answer conflicts with the CV, ask about that difference and set answered false. "
    "If the answer also covers a later checklist item, include that exact item in covered. "
    "Look at what the candidate just said before you choose the next checklist item. "
    "If it answers the open checklist question, set answered true. "
    "Then ask one natural question about the next uncovered item, and put the open item in covered. "
    "If it is a question, a request, or about the camera, microphone, or anything else, set answered false and leave covered empty. "
    "Answer that in one short sentence. If you cannot know, say so. Do not repeat their question back. "
    "Then ask the same open checklist question again in your own words. "
    "Do not start a new checklist item on that turn. "
    "If they have not spoken yet, set answered false and ask the first checklist item in your own words. "
    "Do not invent requirements. covered may only contain exact checklist items. "
    "When the checklist is covered, or the candidate has answered enough, set done and quiz to true "
    "and ask whether they have a question before the skill quiz."
)
_CLOSE_SYSTEM = (
    "The interview questions are finished. You are still on the video call and can see and hear them. "
    "Answer the candidate in one short spoken sentence. "
    "Never say you are a text interface, a chatbot, or an AI that cannot see or hear. "
    "If you cannot know, say so. Do not ask a new question. "
    "Return only a JSON object with the key say."
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
_CALL_CHECKS = (
    "my camera",
    "my video",
    "my mic",
    "my microphone",
    "hear me",
    "see me",
    "you hear",
    "you see",
    "visible",
    "am i visible",
)
_TEXT_DENIALS = (
    "text interface",
    "text-based",
    "text based",
    "language model",
    "chatbot",
    "as an ai",
    "i'm an ai",
    "i am an ai",
    "can't see",
    "cannot see",
    "can not see",
    "don't have eyes",
    "do not have eyes",
    "can't hear you",
    "cannot hear you",
    "only have text",
    "text only",
)
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
_THIN_PHRASES = _FILLERS | {
    "i don't know",
    "i dont know",
    "don't know",
    "dont know",
    "not sure",
    "i'm not sure",
    "im not sure",
    "no idea",
    "nothing",
    "pass",
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
    probed: tuple[str, ...] = ()


@dataclass(frozen=True)
class Utterance:
    say: str
    covered: tuple[str, ...]
    finished: bool
    offer_quiz: bool
    answered: bool = False
    asks: str = ""
    probe: str = ""


def opening_line(company: str, job_title: str, candidate_name: str, first_question: str = "") -> str:
    """Greet the candidate and wait. The first question is spoken after they settle."""
    _ = first_question
    name = " ".join(candidate_name.split()) or "there"
    role = " ".join(job_title.split()) or "this"
    company_name = " ".join(company.split()) or "the company"
    return (
        f"Hello {name}. I am the AI interviewer for the {role} role at {company_name}. "
        "I will ask a few questions, and then there is a short skill quiz. Whenever you are ready."
    )


def acknowledgement(index: int) -> str:
    return _ACKS[index % len(_ACKS)]


def silence_nudge(quiet_count: int) -> str:
    return _NUDGES[max(0, quiet_count - 1) % len(_NUDGES)]


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
        probed=agenda.probed,
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


def candidate_declined(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    return any(phrase in lowered for phrase in ("rather not", "prefer not", "don't want to say", "do not want to say"))


def thin_answer(text: str) -> bool:
    """True when the turn is too small to count as an example."""
    cleaned = " ".join(text.split()).strip(".! ").lower()
    if not cleaned or cleaned in _GREETINGS:
        return False
    if cleaned in _THIN_PHRASES:
        return True
    words = [word.strip(",") for word in cleaned.split()]
    return len(words) <= 2 and all(word in _FILLERS for word in words)


def turn_is_answer(text: str) -> bool:
    """True when this turn should move the checklist forward."""
    cleaned = " ".join(text.split()).strip(".! ")
    if not cleaned or cleaned.lower() in _GREETINGS or thin_answer(text) or candidate_declined(text):
        return False
    return not candidate_asked(text)


def should_acknowledge(text: str) -> bool:
    """A real answer gets a short sound before the next question is ready."""
    return turn_is_answer(text)


def echoes_prompt(heard: str, spoken: str) -> bool:
    """True when the microphone mostly played the interviewer's own last line back."""
    heard_words = heard.lower().split()
    spoken_words = set(spoken.lower().split())
    if len(heard_words) < 6 or not spoken_words:
        return False
    overlap = sum(1 for word in heard_words if word in spoken_words)
    return overlap / len(heard_words) >= 0.75


def interruption_is_noise(heard: str, spoken: str) -> bool:
    """True when talk-over was a cough, an echo, or too short to be a turn."""
    cleaned = " ".join(heard.split()).strip()
    if not cleaned or echoes_prompt(cleaned, spoken):
        return True
    return len(cleaned.strip(".!?").split()) < 3


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
    if heard.strip() and (candidate_declined(heard) or thin_answer(heard)):
        utterance = fallback_utterance(agenda, heard=heard)
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


async def closing_reply(
    llm: FallbackLLMManager,
    *,
    company: str,
    job_title: str,
    heard: str,
) -> str:
    """One short answer after the questions are done."""
    cleaned = " ".join(heard.split())
    if not cleaned:
        return ""
    prompt = f"Company: {company}\nRole: {job_title}\nCandidate said:\n{cleaned}"
    say = ""
    try:
        response = await llm.complete_live(prompt, system=_CLOSE_SYSTEM)
        payload = parse_json_object(response.content)
        say = spoken_limit(_text(payload.get("say")))
    except (JobGraphError, Exception) as exc:
        logger.warning("interviewer_closing_failed error_type=%s", type(exc).__name__)
    if not say or _reads_rubric(say) or copies_candidate(say, cleaned) or denies_the_call(say):
        return _aside_reply(cleaned)
    return say


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
    if candidate_declined(heard):
        return _advance(agenda, "That's all right.")
    if thin_answer(heard):
        current = _open_or_next(agenda)
        if current and current not in agenda.probed:
            return Utterance(
                say="Could you walk me through an example?",
                covered=(),
                finished=False,
                offer_quiz=False,
                answered=False,
                asks=current if current not in agenda.asked else "",
                probe=current,
            )
        return _advance(agenda, "Got it.")
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
    return _advance(agenda, "Got it.")


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
        say="That's everything I wanted to ask. Is there anything you want to ask me before the skill quiz?",
        covered=(),
        finished=True,
        offer_quiz=True,
    )


def _advance(agenda: Agenda, lead: str) -> Utterance:
    nxt = _after_answer(agenda)
    if not nxt:
        return _closing()
    question = spoken_question(nxt)
    say = f"{lead} {question}".strip() if lead else question
    return Utterance(say=say, covered=(), finished=False, offer_quiz=False, answered=True, asks=nxt)


def _apply(agenda: Agenda, utterance: Utterance) -> Agenda:
    covered = list(agenda.covered)
    asked = list(agenda.asked)
    answers = agenda.answers
    probed = list(agenda.probed)
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
    if utterance.probe and utterance.probe in _source(agenda) and utterance.probe not in probed:
        probed.append(utterance.probe)
    return Agenda(
        questions=agenda.questions,
        covered=tuple(covered),
        asked=tuple(asked),
        answers=answers,
        probed=tuple(probed),
    )


def _remaining(agenda: Agenda) -> tuple[str, ...]:
    return tuple(item for item in _source(agenda) if item not in agenda.covered and item not in agenda.asked)


def _source(agenda: Agenda) -> tuple[str, ...]:
    return agenda.questions or GENERAL_QUESTIONS


_FIRST_PERSON = re.compile(r"\b(i|i['’]m|i['’]ve|i['’]ll|i['’]d|my)\b", re.IGNORECASE)


def _slips_into_first_person(say: str) -> bool:
    """True when the reply talks as if the interviewer did the candidate's work."""
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


def denies_the_call(say: str) -> bool:
    """True when a line claims the interviewer has no camera or is only text."""
    lowered = say.lower()
    return any(phrase in lowered for phrase in _TEXT_DENIALS)


def _about_the_call(heard: str) -> bool:
    lowered = heard.lower()
    return any(phrase in lowered for phrase in ("camera", "video", "visible", "see me", "see my", "you see", "hear", "mic", "microphone", "audio"))


def _aside_reply(heard: str) -> str:
    """A short answer for a turn that is not an answer to the checklist."""
    lowered = heard.lower()
    if any(phrase in lowered for phrase in ("see", "visible", "camera", "video")):
        return "Yes. I can see you."
    if any(phrase in lowered for phrase in ("hear", "mic", "microphone", "audio", "sound")):
        return "Yes. I can hear you."
    return "I don't have that in front of me."


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
        if denies_the_call(utterance.say):
            return Utterance(
                say=_aside_reply(heard) if _about_the_call(heard) else "Yes. I can see you.",
                covered=utterance.covered,
                finished=True,
                offer_quiz=utterance.offer_quiz,
                answered=utterance.answered,
                asks=utterance.asks,
                probe=utterance.probe,
            )
        return utterance
    if not answered:
        current = _open_or_next(agenda)
        question = spoken_question(current) if current else ""
        say = utterance.say or question
        if denies_the_call(say):
            say = _aside_reply(heard) if _about_the_call(heard) else "Yes. I can see you."
        elif _reads_rubric(say) or (candidate_asked(heard) and copies_candidate(say, heard)):
            say = _aside_reply(heard) if candidate_asked(heard) else question
        if current and question.lower() not in say.lower() and heard.strip():
            say = f"{say.rstrip()} {question}"
        asks = current if current not in agenda.asked else ""
        return Utterance(say=say, covered=(), finished=False, offer_quiz=False, answered=False, asks=asks)
    allowed = set(_source(agenda))
    extra = tuple(item for item in utterance.covered if item in allowed)
    open_item = _open_item(agenda)
    covered_now = tuple(dict.fromkeys((*agenda.covered, *extra, *((open_item,) if open_item else ()))))
    nxt = _after_answer(
        Agenda(
            questions=agenda.questions,
            covered=covered_now,
            asked=agenda.asked,
            answers=agenda.answers,
            probed=agenda.probed,
        )
    )
    if not nxt:
        return _closing()
    question = spoken_question(nxt)
    say = _drop_ok_so(utterance.say or "")
    if denies_the_call(say):
        say = _aside_reply(heard) if _about_the_call(heard) else "Yes. I can see you."
    if not say or _reads_rubric(say) or copies_candidate(say, heard) or _slips_into_first_person(say):
        say = f"Got it. {question}"
    return Utterance(say=say, covered=extra, finished=False, offer_quiz=False, answered=True, asks=nxt)


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
