from app.services.transcript_cleanup import is_disfluency_only, pair_speech, substantive


def test_disfluency_words_are_noise_and_a_real_answer_keeps_its_words() -> None:
    assert is_disfluency_only("uhm")
    assert is_disfluency_only("uhh, um")
    assert is_disfluency_only("Yes.") is False
    assert substantive("uhh, so I shipped a FastAPI service.") == "I shipped a FastAPI service."
    assert substantive("I uh containerized that service.") == "I containerized that service."
    assert substantive("Yes.") == "Yes."


def test_filler_asides_and_echoes_pair_like_the_clean_transcript() -> None:
    clean = [
        ("recruiter", "How have you used FastAPI?", 1.0, 3.0),
        ("candidate", "I shipped a FastAPI service with PostgreSQL.", 3.5, 8.0),
        ("recruiter", "And Docker?", 9.0, 11.0),
        ("candidate", "I containerized that service with Docker Compose.", 11.5, 16.0),
    ]
    noisy = [
        ("recruiter", "How have you used FastAPI?", 1.0, 3.0),
        ("candidate", "uhm", 3.2, 3.6),
        ("recruiter", "Take your time.", 3.6, 4.2),
        ("candidate", "uhh, so I shipped a FastAPI service with PostgreSQL.", 4.4, 8.0),
        ("candidate", "uhh", 8.0, 8.4),
        ("recruiter", "Okay.", 9.0, 9.4),
        ("recruiter", "And Docker?", 9.4, 11.0),
        ("candidate", "And Docker?", 11.2, 12.0),
        ("candidate", "I uh containerized that service with Docker Compose.", 12.0, 16.0),
    ]
    assert [(item.question, item.answer) for item in pair_speech(noisy)] == [
        (item.question, item.answer) for item in pair_speech(clean)
    ]
