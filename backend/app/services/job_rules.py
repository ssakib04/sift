class ChecklistLockedError(RuntimeError):
    """A frozen checklist cannot be edited in place."""


def ensure_editable(status: str) -> None:
    if status != "draft":
        raise ChecklistLockedError("This checklist is frozen. Create a new job version to change it.")


def ensure_can_open_version(latest_status: str) -> None:
    if latest_status != "locked":
        raise ChecklistLockedError("Approve the current draft before opening another version.")
