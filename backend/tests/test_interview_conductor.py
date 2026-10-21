import pytest

from app.core.llm_fallback import FallbackLLMManager
from app.services.interview_conductor import (
    Agenda,
    answer_limit,
    echoes_prompt,
    fallback_utterance,
    first_question,
    note_answer,
    opening_line,
    plan_reply,
    spoken_limit,
    spoken_question,
    spoken_sentences,
    utterance_from_model,
)


class _Provider:
    def __init__(self, text: str) -> None:
        self.text = text

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.prompt = prompt
        self.system = system
        return self.text


class _Boom:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        raise RuntimeError("model down")


def test_opening_line_names_the_ai_and_asks_the_first_question() -> None:
    line = opening_line("Sift", "Backend engineer", "Amina Rahman", "How do you test a service?")
    assert "AI interviewer" in line
    assert "Amina Rahman" in line
    assert "Backend engineer" in line
    assert "Sift" in line
    assert line.endswith("How do you test a service?")


def test_opening_line_waits_for_a_real_question_when_none_is_ready() -> None:
    line = opening_line("Sift", "Backend engineer", "Amina Rahman")
    assert "AI interviewer" in line
    assert "the candidate" not in line.lower()
    assert not line.endswith("?")


def test_spoken_question_addresses_the_candidate() -> None:
    asked = spoken_question("Does the candidate demonstrate strong Python programming skills?")
    assert asked == "Do you demonstrate strong Python programming skills?"
    assert spoken_question("Can the candidate build machine learning models?") == "Can you build machine learning models?"
    line = opening_line("Sift", "ML engineer", "Amina Rahman", asked)
    assert "the candidate" not in line.lower()
    assert line.endswith(asked)


def test_fallback_asks_the_candidate_instead_of_reading_the_rubric() -> None:
    agenda = note_answer(
        Agenda(
            questions=(
                "Does the candidate demonstrate strong Python programming skills?",
                "Can the candidate build machine learning models?",
            ),
            asked=("Does the candidate demonstrate strong Python programming skills?",),
        )
    )
    utterance = fallback_utterance(agenda)
    assert utterance.say == "Can you build machine learning models?"
    assert "candidate" not in utterance.say.lower()


@pytest.mark.asyncio
async def test_plan_reply_rewrites_a_rubric_the_model_reads_aloud() -> None:
    provider = _Provider(
        '{"say": "Does the candidate demonstrate strong Python programming skills?", "covered": [], "done": false, "quiz": false}'
    )
    agenda = Agenda(
        questions=(
            "Does the candidate demonstrate strong Python programming skills?",
            "Can the candidate build machine learning models?",
        )
    )
    utterance, _advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="ML engineer",
        profile="",
        transcript="",
        heard="Hello.",
    )
    assert utterance.say == "Do you demonstrate strong Python programming skills?"
    assert "the candidate" not in utterance.say.lower()


def test_opening_line_uses_a_general_question_when_the_checklist_is_empty() -> None:
    assert first_question(()) == "Tell me about a recent project you are proud of."


def test_echo_of_the_prompt_is_ignored_and_a_short_answer_is_kept() -> None:
    spoken = "How do you test a service that writes to a database?"
    assert echoes_prompt(spoken, spoken) is True
    assert echoes_prompt("Yes, with pytest.", spoken) is False


def test_fallback_walks_the_checklist_then_closes_with_the_quiz() -> None:
    agenda = Agenda(questions=("Can you write tests?", "Can you review a pull request?"), asked=("Can you write tests?",))
    nxt = fallback_utterance(note_answer(agenda))
    assert nxt.say == "Can you review a pull request?"
    assert nxt.finished is False
    covered = Agenda(
        questions=agenda.questions,
        covered=agenda.questions,
        asked=agenda.questions,
        answers=2,
    )
    closing = fallback_utterance(covered)
    assert closing.finished is True
    assert closing.offer_quiz is True
    assert "skill quiz" in closing.say


@pytest.mark.asyncio
async def test_plan_reply_uses_the_model_question() -> None:
    provider = _Provider(
        '{"say": "Which database did you use?", "covered": ["Can you write tests?"], "done": false, "quiz": false}'
    )
    agenda = note_answer(Agenda(questions=("Can you write tests?", "Can you review a pull request?"), asked=("Can you write tests?",)))
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="Amina Rahman\nBuilt billing services.",
        transcript="recruiter: Can you write tests?",
        heard="I use pytest for every service.",
    )
    assert "Which database did you use?" in utterance.say
    assert "pytest" in utterance.say.lower()
    assert "Can you write tests?" in advanced.covered
    assert "I use pytest for every service." in provider.prompt


@pytest.mark.asyncio
async def test_plan_reply_asks_the_checklist_when_the_model_fails() -> None:
    agenda = note_answer(
        Agenda(
            questions=("Can you write tests?", "Can you review a pull request?"),
            asked=("Can you write tests?",),
        )
    )
    utterance, _advanced = await plan_reply(
        FallbackLLMManager(_Boom(), _Boom(), _Boom()),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="",
        heard="Yes.",
    )
    assert "Can you review a pull request?" in utterance.say
    assert utterance.finished is False


def test_model_payload_marks_the_quiz_when_the_interview_is_done() -> None:
    agenda = Agenda(questions=("Can you write tests?",), answers=1)
    utterance = utterance_from_model(agenda, {"say": "Thanks.", "covered": ["Can you write tests?"], "done": True, "quiz": True})
    assert utterance.finished is True
    assert utterance.offer_quiz is True
    assert utterance.covered == ("Can you write tests?",)


def test_model_cannot_end_the_interview_before_the_question_limit() -> None:
    agenda = Agenda(questions=("Can you write tests?", "Can you review a pull request?"), answers=1, asked=("Can you write tests?",))
    utterance = utterance_from_model(
        agenda,
        {"say": "What was hardest about that?", "covered": ["Can you write tests?"], "done": True, "quiz": True},
    )
    assert utterance.finished is False
    assert utterance.offer_quiz is False
    assert utterance.say == "What was hardest about that?"


def test_model_payload_drops_requirements_that_are_not_on_the_checklist() -> None:
    agenda = Agenda(questions=("Can you write tests?",))
    utterance = utterance_from_model(agenda, {"say": "Next?", "covered": ["Invented skill"], "done": False})
    assert utterance.covered == ()


def test_spoken_limit_keeps_a_whole_sentence() -> None:
    text = ("This answer is long. " * 40).strip()
    limited = spoken_limit(text, max_chars=80)
    assert limited.endswith(".")
    assert len(limited) <= 80


def test_answer_limit_follows_the_checklist_and_caps() -> None:
    assert answer_limit(Agenda(questions=tuple(f"Q{index}" for index in range(12)))) == 8
    assert answer_limit(Agenda(questions=())) == 3


@pytest.mark.asyncio
async def test_a_paraphrased_question_counts_as_the_next_checklist_item() -> None:
    agenda = note_answer(
        Agenda(
            questions=(
                "Can the candidate build machine learning models?",
                "Does the candidate write tests?",
            ),
            asked=("Can the candidate build machine learning models?",),
        )
    )
    provider = _Provider('{"say": "Have you shipped a model?", "covered": [], "done": false, "quiz": false}')
    _utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="ML engineer",
        profile="",
        transcript="",
        heard="I trained one classifier.",
    )
    assert "Have you shipped a model?" in _utterance.say
    assert "classifier" in _utterance.say.lower()
    assert "Does the candidate write tests?" in advanced.asked


@pytest.mark.asyncio
async def test_a_candidate_question_does_not_skip_the_checklist() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    provider = _Provider(
        '{"say": "The team uses Postgres.", "answered": true, "covered": ["Can you write tests?"], "done": false, "quiz": false}'
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="recruiter: Can you write tests?",
        heard="What database does the team use?",
    )
    assert "Can you write tests?" in utterance.say
    assert "Can you write tests?" not in advanced.covered
    assert advanced.asked == ("Can you write tests?",)
    assert advanced.answers == 0


@pytest.mark.asyncio
async def test_a_real_answer_is_restated_in_the_second_person() -> None:
    agenda = Agenda(
        questions=("Do you have 7 years of experience?", "Can you write tests?"),
        asked=("Do you have 7 years of experience?",),
    )
    provider = _Provider(
        '{"say": "yes i have 10 years of experience", "answered": true, "covered": ["Do you have 7 years of experience?"], "done": false, "quiz": false}'
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="recruiter: Do you have 7 years of experience?",
        heard="yes i have 10 years of experience",
    )
    assert utterance.say.lower().startswith("so you have 10 years")
    assert "yes i have" not in utterance.say.lower()
    assert "Can you write tests?" in utterance.say
    assert "Do you have 7 years of experience?" in advanced.covered


@pytest.mark.asyncio
async def test_a_mid_sentence_copy_stays_in_the_second_person() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    heard = "I've built the billing service and I have done the on-call rotation"
    provider = _Provider(
        '{"say": "Ok so you\'ve built the billing service and I have done the on-call rotation", "answered": true, "covered": [], "done": false, "quiz": false}'
    )
    utterance, _advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="recruiter: Can you write tests?",
        heard=heard,
    )
    spoken = utterance.say.lower()
    assert spoken.startswith("so you have built the billing service and you have done the on-call rotation")
    assert " i " not in f" {spoken} "
    assert "Can you review a pull request?" in utterance.say


@pytest.mark.asyncio
async def test_a_camera_question_is_answered_and_the_same_question_returns() -> None:
    agenda = Agenda(
        questions=("Do you have 7 years of experience?", "Can you write tests?"),
        asked=("Do you have 7 years of experience?",),
    )
    provider = _Provider(
        '{"say": "is my camera alright", "answered": true, "covered": ["Do you have 7 years of experience?"], "done": false, "quiz": false}'
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="recruiter: Do you have 7 years of experience?",
        heard="is my camera alright",
    )
    assert "camera" in utterance.say.lower()
    assert "is my camera alright" not in utterance.say.lower()
    assert "Do you have 7 years of experience?" in utterance.say
    assert "Can you write tests?" not in utterance.say
    assert advanced.covered == ()
    assert advanced.answers == 0


def test_spoken_sentences_start_with_the_first_sentence() -> None:
    parts = spoken_sentences("That is a clear example. How did you test the model before you shipped it?")
    assert parts[0] == "That is a clear example."
    assert parts[1].startswith("How did you")
