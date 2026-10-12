from dataclasses import dataclass

from app.core.llm_fallback import FallbackLLMManager
from app.graphs.job_creation_graph import JobGraphError, parse_json_object


@dataclass(frozen=True)
class CopilotDraft:
    explored: list[str]
    gaps: list[str]
    suggested_question: str


def copilot_without_speech(questions: list[str]) -> CopilotDraft:
    return CopilotDraft(
        explored=[],
        gaps=list(questions),
        suggested_question=questions[0] if questions else "",
    )


async def copilot_from_transcript(
    llm: FallbackLLMManager,
    questions: list[str],
    transcript: str,
) -> CopilotDraft:
    if not transcript.strip():
        return copilot_without_speech(questions)
    checklist = "\n".join(f"- {question}" for question in questions)
    prompt = (
        "Compare the interview transcript with the locked requirements. "
        "Return JSON with keys explored (list of requirements already discussed), "
        "gaps (list of requirements not yet discussed), and suggested_question "
        "(one question the recruiter should ask next). "
        "Do not invent requirements that are not in the checklist.\n"
        f"Checklist:\n{checklist}\n\nTranscript:\n{transcript}"
    )
    response = await llm.complete(
        prompt,
        system="You assist a recruiter during a live interview. Return only a JSON object.",
    )
    try:
        payload = parse_json_object(response.content)
    except JobGraphError:
        return copilot_without_speech(questions)
    return CopilotDraft(
        explored=_strings(payload.get("explored")),
        gaps=_strings(payload.get("gaps")),
        suggested_question=_text(payload.get("suggested_question")),
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()
