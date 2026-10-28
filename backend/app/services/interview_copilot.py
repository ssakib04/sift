from dataclasses import dataclass

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import JobGraphError, parse_json_object
from app.services.interview_rules import InterviewError
from app.services.question_bank import prefer_bank_list, prefer_bank_question, related_bank_questions

_PROFILE_LIMIT = 6000
_EMPTY_PROFILE = "No CV is stored for this person."


@dataclass(frozen=True)
class CopilotDraft:
    explored: list[str]
    gaps: list[str]
    suggested_question: str
    profile_available: bool = True


@dataclass(frozen=True)
class CopilotAnswer:
    reply: str
    questions: list[str]
    profile_available: bool


def cv_profile_text(name: str, raw_text: str) -> str:
    """The stored CV text the copilot may use. Blank when this person has no CV."""
    body = " ".join(raw_text.split())
    if not body:
        return ""
    who = " ".join(name.split()) or "Candidate"
    return f"{who}\n{body[:_PROFILE_LIMIT]}"


def normalize_copilot_ask(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned or len(cleaned) > 2000:
        raise InterviewError("COPILOT_QUESTION_REQUIRED", "Ask the copilot for a question.", 400)
    return cleaned


def copilot_without_speech(questions: list[str], *, profile_available: bool = True) -> CopilotDraft:
    return CopilotDraft(
        explored=[],
        gaps=list(questions),
        suggested_question=questions[0] if questions else "",
        profile_available=profile_available,
    )


async def copilot_from_transcript(
    llm: FallbackLLMManager,
    questions: list[str],
    transcript: str,
    profile: str = "",
    bank: list[str] | None = None,
) -> CopilotDraft:
    available = bool(profile.strip())
    stored = list(bank or [])
    if not transcript.strip():
        draft = copilot_without_speech(questions, profile_available=available)
        return _with_bank(draft, stored, transcript)
    checklist = "\n".join(f"- {question}" for question in questions)
    prompt = (
        "Compare the interview transcript with the locked requirements and the CV profile. "
        "Return JSON with keys explored (list of requirements already discussed), "
        "gaps (list of requirements not yet discussed), and suggested_question "
        "(one question the recruiter should ask next). "
        "explored and gaps must only use the checklist. "
        "suggested_question should test a skill the CV claims when the transcript has not covered it. "
        "When a company question bank question is related, copy that question as written. "
        "If none is related, write your own. "
        "Do not invent skills that are not in the CV or the checklist.\n"
        f"{_profile_block(profile)}\n"
        f"{_bank_block(stored, ' '.join(questions))}\n"
        f"Checklist:\n{checklist}\n\nTranscript:\n{transcript}"
    )
    response = await llm.complete(
        prompt,
        system="You assist a recruiter during a live interview. Return only a JSON object.",
    )
    try:
        payload = parse_json_object(response.content)
    except JobGraphError:
        return _with_bank(copilot_without_speech(questions, profile_available=available), stored, transcript)
    draft = CopilotDraft(
        explored=_strings(payload.get("explored")),
        gaps=_strings(payload.get("gaps")),
        suggested_question=_text(payload.get("suggested_question")),
        profile_available=available,
    )
    return _with_bank(draft, stored, transcript)


async def ask_copilot(
    llm: FallbackLLMManager,
    checklist: list[str],
    transcript: str,
    profile: str,
    question: str,
    bank: list[str] | None = None,
) -> CopilotAnswer:
    """Answer the recruiter from the CV, the checklist, and the transcript so far."""
    asked = normalize_copilot_ask(question)
    available = bool(profile.strip())
    stored = list(bank or [])
    listed = "\n".join(f"- {item}" for item in checklist) or "- (no locked checklist)"
    prompt = (
        "The recruiter asked for help during a live interview. "
        "Use the CV profile, the locked checklist, and the transcript, including lines still being spoken. "
        "Suggest questions that follow what has already been asked and that test skills the CV claims "
        "when those skills have not yet been discussed. Do not repeat a question already asked. "
        "When a company question bank question is related, copy that question as written. "
        "If none is related, write your own. "
        "Do not invent skills that are not in the CV or the checklist. "
        "Return JSON with keys reply (string) and questions (list of at most 5 strings).\n"
        f"Recruiter request:\n{asked}\n\n"
        f"{_profile_block(profile)}\n"
        f"{_bank_block(stored, asked + ' ' + ' '.join(checklist))}\n"
        f"Checklist:\n{listed}\n\n"
        f"Transcript:\n{transcript.strip() or '(no speech yet)'}"
    )
    response = await llm.complete(
        prompt,
        system="You assist a recruiter during a live interview. Return only a JSON object.",
    )
    try:
        payload = parse_json_object(response.content)
    except JobGraphError:
        payload = {}
    reply = _text(payload.get("reply"))
    questions = prefer_bank_list(_strings(payload.get("questions")), asked + " " + " ".join(checklist), stored, transcript)[:5]
    if not reply:
        reply = "The copilot could not read a response. Ask again."
    if not available and _EMPTY_PROFILE not in reply:
        reply = f"{_EMPTY_PROFILE} {reply}"
    return CopilotAnswer(reply=reply, questions=questions, profile_available=available)


def _with_bank(draft: CopilotDraft, bank: list[str], transcript: str) -> CopilotDraft:
    topic = draft.gaps[0] if draft.gaps else draft.suggested_question
    suggested = prefer_bank_question(draft.suggested_question, topic, bank, transcript)
    if suggested == draft.suggested_question:
        return draft
    return CopilotDraft(
        explored=draft.explored,
        gaps=draft.gaps,
        suggested_question=suggested,
        profile_available=draft.profile_available,
    )


def _bank_block(bank: list[str], topic: str) -> str:
    related = related_bank_questions(topic, bank)
    if not related:
        return "Company question bank: no related question. Write the next question yourself."
    listed = "\n".join(f"- {question}" for question in related)
    return f"Company question bank. Use a related question as written:\n{listed}"


def _profile_block(profile: str) -> str:
    if not profile.strip():
        return (
            f"CV profile: {_EMPTY_PROFILE} "
            "Say that the profile is empty and use only the transcript and the checklist."
        )
    return f"CV profile:\n{profile}"


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()
