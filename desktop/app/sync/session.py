"""Cancellation of a desktop synchronization = stop + restore the state from before it started.

  1. POST /sync/{id}/cancel            RUNNING → CANCEL_REQUESTED (no further changes accepted)
  2. (the executor stops after the change in progress)
  3. POST /sync/{id}/rollback          → ROLLING_BACK; the server reverses the remote changes
  4. LocalJournal.rollback()           the desktop reverses its local changes
  5. POST /sync/{id}/rollback/finish   → CANCELLED, or ROLLBACK_FAILED with the details

Every step is idempotent, so the same function also resumes an interrupted rollback.
Runs in a worker thread (blocking HTTP and filesystem calls).
"""

from dataclasses import dataclass, field
from typing import Callable

from app.sync.journal import LocalJournal

UNFINISHED = {"PENDING", "RUNNING", "CANCEL_REQUESTED", "ROLLING_BACK", "ROLLBACK_FAILED"}


@dataclass
class RollbackOutcome:
    status: str
    details: dict
    failures: list[dict] = field(default_factory=list)  # {relative_path, operation, code, side}


def request_cancel(api, synchronization_id: str) -> None:
    try:
        api.cancel_sync(synchronization_id)
    except Exception as exc:
        if getattr(exc, "code", None) != "sync_cancelled":
            raise


def rollback_synchronization(
    api,
    synchronization_id: str,
    journal: LocalJournal | None,
    on_restoring: Callable[[], None] = lambda: None,
    restore_local: bool = True,
    counts: dict | None = None,
) -> RollbackOutcome:
    on_restoring()
    api.rollback_sync(synchronization_id)

    local_restored, local_failures = 0, []
    if journal is not None and restore_local:
        local_restored, failed = journal.rollback()
        local_failures = [
            {"relative_path": e.path, "operation": e.kind, "code": e.error or "local_io_error"} for e in failed
        ]
    elif journal is not None:
        local_failures = [{"relative_path": journal.data.local_root, "operation": "LOCAL_ROLLBACK",
                           "code": "local_permission_denied"}]

    details = api.finish_rollback(synchronization_id, local_restored, local_failures, counts)
    if details["status"] == "CANCELLED" and journal is not None:
        journal.discard()

    report = details.get("rollback_report") or {}
    failures = [{**f, "side": "remote"} for f in report.get("remote_failures", [])]
    failures += [{**f, "side": "local"} for f in report.get("local_failures", [])]
    return RollbackOutcome(details["status"], details, failures)


def cancel_and_rollback(api, synchronization_id: str, journal: LocalJournal | None,
                        on_restoring: Callable[[], None] = lambda: None,
                        restore_local: bool = True, counts: dict | None = None) -> RollbackOutcome:
    request_cancel(api, synchronization_id)
    return rollback_synchronization(api, synchronization_id, journal, on_restoring, restore_local, counts)


def pending_recoveries(api, root_dir=None) -> list[tuple[LocalJournal, str]]:
    """Journals of interrupted synchronizations that still need a rollback (or a decision)."""
    found = []
    for journal in LocalJournal.list_stored(root_dir):
        try:
            details = api.get_synchronization(journal.data.synchronization_id)
        except Exception as exc:
            if getattr(exc, "status_code", None) in (403, 404):
                journal.discard()
            continue
        if details["status"] in UNFINISHED:
            found.append((journal, details["status"]))
        else:
            journal.discard()
    return found
