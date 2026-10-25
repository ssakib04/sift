"""Progress of the reports that start when an interview ends."""

REPORT_STEPS = ("qa", "claims", "score", "quality", "assessment")
_REPORT_STATES = {"pending", "ready", "failed"}


def initial_report_progress() -> dict[str, str]:
    """Every post-call report starts unwritten."""
    return {step: "pending" for step in REPORT_STEPS}


def advance_report_progress(progress: dict[str, str] | None, step: str, state: str) -> dict[str, str]:
    """Record one report as pending, ready, or failed."""
    if step not in REPORT_STEPS or state not in _REPORT_STATES:
        raise ValueError("Unknown report step.")
    updated = initial_report_progress()
    for key, value in (progress or {}).items():
        if key in REPORT_STEPS and value in _REPORT_STATES:
            updated[key] = value
    updated[step] = state
    return updated


def reports_still_writing(progress: dict[str, str] | None) -> bool:
    current = progress or {}
    return any(current.get(step) == "pending" for step in REPORT_STEPS)


def visible_report_progress(status: str, stored: dict[str, str] | None) -> dict[str, str]:
    """Show saved progress only after the interview has ended."""
    if status != "ended" or not stored:
        return {}
    return {step: stored[step] for step in REPORT_STEPS if stored.get(step) in _REPORT_STATES}
