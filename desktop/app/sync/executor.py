"""Executes a synchronization plan returned by POST /sync on the local machine.

Every change can be reversed: remote changes are journaled by the server (the
synchronization_id is sent with uploads/deletes), local changes by the LocalJournal
before they happen. Cancellation (should_stop) is checked before every change; a
change already in progress finishes and is reversed by the rollback as well.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.sync.journal import LocalJournal
from app.sync.scanner import to_iso_utc

UPLOAD_LOCAL = "UPLOAD_LOCAL"
DOWNLOAD_REMOTE = "DOWNLOAD_REMOTE"
DELETE_REMOTE = "DELETE_REMOTE"
DELETE_LOCAL = "DELETE_LOCAL"
UNCHANGED = "UNCHANGED"


class Stopped(Exception):
    """The cancel request arrived before this change modified anything."""


@dataclass
class SyncResult:
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)
    # set when the result could not be stored in the synchronization history
    history_error: str | None = None
    # raw exceptions per failed path (for translated messages in the UI)
    exceptions: dict[str, BaseException] = field(default_factory=dict)
    stopped: bool = False

    def add(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def history_counts(self) -> dict:
        """Counts in the shape of PATCH /synchronizations/{id}."""
        return {
            "uploaded": self.counts.get(UPLOAD_LOCAL, 0),
            "downloaded": self.counts.get(DOWNLOAD_REMOTE, 0),
            "deleted_local": self.counts.get(DELETE_LOCAL, 0),
            "deleted_remote": self.counts.get(DELETE_REMOTE, 0),
            "unchanged": self.counts.get(UNCHANGED, 0),
            "failed": len(self.errors),
        }

    def summary(self) -> str:
        labels = {
            UPLOAD_LOCAL: "uploaded",
            DOWNLOAD_REMOTE: "downloaded",
            DELETE_REMOTE: "deleted remotely",
            DELETE_LOCAL: "deleted locally",
            UNCHANGED: "unchanged",
        }
        parts = [f"{self.counts.get(k, 0)} {label}" for k, label in labels.items()]
        if self.errors:
            parts.append(f"{len(self.errors)} failed")
        return ", ".join(parts)


def _cancelled_by_server(exc: BaseException) -> bool:
    return getattr(exc, "code", None) == "sync_cancelled"


class SyncExecutor:

    def __init__(
        self,
        api,
        local_root: Path,
        remote_folder_id: str,
        synchronization_id: str | None = None,
        journal: LocalJournal | None = None,
        should_stop: Callable[[], bool] = lambda: False,
    ):
        self.api = api
        self.root = Path(local_root).resolve()
        self.remote_folder_id = remote_folder_id
        self.synchronization_id = synchronization_id
        self.journal = journal
        self.should_stop = should_stop
        # the exception of the change that just failed (for translated messages in the UI)
        self.last_exception: BaseException | None = None

    def local_path(self, relative_path: str) -> Path:
        """Path inside the local root; refuses anything that escapes it."""
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Path escapes the synchronized folder: {relative_path}")
        return path

    def execute(
        self,
        plan: dict,
        on_progress: Callable[[int, dict, str | None], None] | None = None,
        on_start: Callable[[int, dict], None] | None = None,
    ) -> SyncResult:
        """Run every change; one failed file does not stop the others, a cancel stops before the next.

        on_start(index, change) before a change, on_progress(index, change, error) after it.
        """
        result = SyncResult()
        for index, change in enumerate(plan["changes"]):
            if change["kind"] != UNCHANGED and self.should_stop():
                result.stopped = True
                break
            if on_start and change["kind"] != UNCHANGED:
                on_start(index, change)
            error = None
            try:
                self.apply(change)
                result.add(change["kind"])
            except Exception as exc:
                if isinstance(exc, Stopped) or _cancelled_by_server(exc):
                    result.stopped = True
                    break
                error = str(exc)
                self.last_exception = exc
                result.errors.append((change["relative_path"], error))
                result.exceptions[change["relative_path"]] = exc
            if on_progress:
                on_progress(index, change, error)
        return result

    def apply(self, change: dict) -> None:
        kind = change["kind"]

        if kind == UPLOAD_LOCAL:
            self.upload_local_file(change)

        elif kind == DOWNLOAD_REMOTE:
            self.download_remote_file(change)

        elif kind == DELETE_REMOTE:
            self.delete_remote_file(change)

        elif kind == DELETE_LOCAL:
            self.delete_local_file(change)

        # UNCHANGED: nothing to do

    def _sync_kwargs(self) -> dict:
        return {"synchronization_id": self.synchronization_id} if self.synchronization_id else {}

    def upload_local_file(self, change: dict) -> None:
        path = self.local_path(change["relative_path"])
        relative_dir = Path(change["relative_path"]).parent.as_posix()
        self.api.upload_file(
            path,
            folder_id=self.remote_folder_id,
            relative_dir=None if relative_dir == "." else relative_dir,
            # keep the local mtime so the next sync sees both sides as equal
            modified_at=to_iso_utc(path.stat().st_mtime),
            **self._sync_kwargs(),
        )

    def download_remote_file(self, change: dict) -> None:
        path = self.local_path(change["relative_path"])
        content = self.api.download_file(change["remote_file_id"])
        if self.should_stop():
            raise Stopped()  # downloaded, but nothing written yet

        entry = self.journal.before_write(change["relative_path"]) if self.journal else None
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".minidrive-part")
        temp.write_bytes(content)
        os.replace(temp, path)

        remote_modified = change.get("remote_modified_at")
        if remote_modified:
            ts = datetime.fromisoformat(remote_modified.replace("Z", "+00:00")).timestamp()
            os.utime(path, (ts, ts))
        if entry is not None:
            self.journal.applied(entry)

    def delete_remote_file(self, change: dict) -> None:
        self.api.delete_file(change["remote_file_id"], **self._sync_kwargs())

    def delete_local_file(self, change: dict) -> None:
        path = self.local_path(change["relative_path"])
        if path.is_file():
            entry = self.journal.before_delete(change["relative_path"]) if self.journal else None
            path.unlink()
            if entry is not None:
                self.journal.applied(entry)
