import pytest

from app.core.llm_fallback import FallbackLLMManager
from app.services.interview_conductor import (
    Agenda,
    answer_beat,
    answer_limit,
    echoes_prompt,
    fallback_utterance,
    first_question,
    interruption_is_noise,
    note_answer,
    opening_line,
    plan_reply,
    settled_turn_kind,
    silence_nudge,
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


def test_opening_line_names_the_ai_and_waits() -> None:
    line = opening_line("Sift", "Backend engineer", "Amina Rahman", "How do you test a service?")
    assert "AI interviewer" in line
    assert "Amina Rahman" in line
    assert "Backend engineer" in line
    assert "Sift" in line
    assert "How do you test a service?" not in line
    assert line.endswith("Whenever you are ready.")


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
    assert asked not in line


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
        '{"say": "Pytest on every service. Which database did you use?", "answered": true, "covered": ["Can you write tests?"], "done": false, "quiz": false}'
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
    assert "Pytest on every service." in utterance.say
    assert "Which database did you use?" in utterance.say
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
        heard="I write tests for every service I ship.",
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
    assert "yes i have" not in utterance.say.lower()
    assert "Do you have 7 years of experience?" in utterance.say
    assert advanced.answers == 0
    assert "Do you have 7 years of experience?" not in advanced.covered


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
    assert "can you write tests?" in spoken
    assert "billing service" not in spoken
    assert _advanced.answers == 0


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
    assert "see you" in utterance.say.lower()
    assert "text" not in utterance.say.lower()
    assert "is my camera alright" not in utterance.say.lower()
    assert "Do you have 7 years of experience?" in utterance.say
    assert "Can you write tests?" not in utterance.say
    assert advanced.covered == ()
    assert advanced.answers == 0


@pytest.mark.asyncio
async def test_a_visibility_question_is_answered_as_a_person_on_the_call() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    provider = _Provider(
        '{"say": "I can\'t see you because this is a text interface.", "answered": false, "covered": [], "done": false, "quiz": false}'
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="recruiter: Can you write tests?",
        heard="am I visible",
    )
    assert "see you" in utterance.say.lower()
    assert "text" not in utterance.say.lower()
    assert "Can you write tests?" in utterance.say
    assert advanced.answers == 0


def test_a_finished_answer_is_not_taken_back() -> None:
    assert settled_turn_kind("answer", "question") == "answer"
    assert settled_turn_kind("answer", "partial") == "answer"
    assert settled_turn_kind("question", "answer") == "answer"
    assert settled_turn_kind("question", "aside") == "question"
    assert answer_beat() > 0


@pytest.mark.asyncio
async def test_a_thin_answer_asks_for_one_example_before_moving_on() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(_Boom(), _Boom(), _Boom()),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="",
        heard="Yes.",
    )
    assert utterance.say == "Could you walk me through an example?"
    assert advanced.answers == 0
    assert advanced.covered == ()
    assert advanced.probed == ("Can you write tests?",)

    follow, moved = await plan_reply(
        FallbackLLMManager(_Boom(), _Boom(), _Boom()),
        advanced,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="",
        heard="No.",
    )
    assert "That does not answer it yet." in follow.say
    assert "Can you write tests?" in follow.say
    assert "Can you write tests?" not in moved.covered
    assert moved.answers == 0


@pytest.mark.asyncio
async def test_a_refusal_moves_on_without_a_second_ask() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(_Boom(), _Boom(), _Boom()),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="",
        heard="I would rather not say.",
    )
    assert utterance.say.startswith("That's all right.")
    assert "Can you review a pull request?" in utterance.say
    assert "Can you write tests?" in advanced.covered


def test_a_cough_is_noise_and_a_sentence_keeps_the_turn() -> None:
    spoken = "How do you test a service that writes to a database?"
    assert interruption_is_noise("uh", spoken) is True
    assert interruption_is_noise("", spoken) is True
    assert interruption_is_noise(spoken, spoken) is True
    assert interruption_is_noise("I write unit tests.", spoken) is False
    assert interruption_is_noise("wait", spoken) is False
    assert interruption_is_noise("hold on", spoken) is False


class _Judge:
    def __init__(self, kind: str, say: str) -> None:
        self.kind = kind
        self.say = say
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt
        self.calls += 1
        if system and "label one interview turn" in system:
            return self.kind
        return self.say


@pytest.mark.asyncio
async def test_a_finished_answer_moves_on_when_the_local_model_would_call_it_a_question() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    provider = _Judge(
        '{"kind": "question"}',
        '{"say": "How do you review a pull request?", "answered": true, "covered": ["Can you write tests?"], "done": false, "quiz": false}',
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="recruiter: Can you write tests?",
        heard="I led the billing migration for two years and I want the team size",
    )
    assert utterance.say == "How do you review a pull request?"
    assert "Can you write tests?" in advanced.covered
    assert advanced.answers == 1
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_a_substantial_answer_moves_on_when_the_local_model_would_call_it_partial() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    provider = _Judge(
        '{"kind": "partial"}',
        '{"say": "Can you review a pull request?", "answered": true, "covered": ["Can you write tests?"], "done": false, "quiz": false}',
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="",
        heard="I have done some testing in a few services.",
    )
    assert utterance.say == "Can you review a pull request?"
    assert advanced.answers == 1
    assert "Can you write tests?" in advanced.covered
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_a_finished_answer_is_not_treated_as_a_refusal() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    provider = _Judge(
        '{"kind": "decline"}',
        '{"say": "Can you review a pull request?", "answered": true, "covered": [], "done": false, "quiz": false}',
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="",
        heard="I led the billing migration for two years.",
    )
    assert utterance.say == "Can you review a pull request?"
    assert "That's all right." not in utterance.say
    assert "Can you write tests?" in advanced.covered
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_a_broken_local_label_uses_the_keyword_rules() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    provider = _Judge(
        "not json",
        '{"say": "Which database did you use?", "answered": true, "covered": [], "done": false, "quiz": false}',
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="",
        heard="I write tests for every service I ship.",
    )
    assert utterance.say == "Which database did you use?"
    assert "Can you write tests?" in advanced.covered
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_a_short_question_stays_on_the_same_item() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    provider = _Judge(
        '{"kind": "question"}',
        '{"say": "That is discussed later. Can you write tests?", "answered": false, "covered": [], "done": false, "quiz": false}',
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(provider, provider, provider),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="",
        heard="What is the salary?",
    )
    assert "Can you write tests?" in utterance.say
    assert advanced.answers == 0
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_a_long_answer_that_opens_with_what_stays_until_it_answers() -> None:
    agenda = Agenda(
        questions=("Can you write tests?", "Can you review a pull request?"),
        asked=("Can you write tests?",),
    )
    utterance, advanced = await plan_reply(
        FallbackLLMManager(_Boom(), _Boom(), _Boom()),
        agenda,
        company="Sift",
        job_title="Backend engineer",
        profile="",
        transcript="",
        heard="What I built was a billing service that handled retries for six months.",
    )
    assert "Can you write tests?" in utterance.say
    assert "Can you write tests?" not in advanced.covered
    assert advanced.answers == 0


def test_silence_nudges_are_not_the_same_line() -> None:
    assert silence_nudge(1) != silence_nudge(2)
    assert "catch" not in silence_nudge(1).lower()


def test_spoken_sentences_start_with_the_first_sentence() -> None:
    parts = spoken_sentences("That is a clear example. How did you test the model before you shipped it?")
    assert parts[0] == "That is a clear example."
    assert parts[1].startswith("How did you")
