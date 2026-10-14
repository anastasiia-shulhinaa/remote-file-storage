"""Write-ahead journal of LOCAL changes made by a desktop synchronization.

The backend reverses remote changes; the desktop reverses what it did to the local
folder (the server never touches the local disk). Before a local file is replaced or
deleted it is copied (with its modification time, shutil.copy2) into the journal
directory, and the journal is written to disk. After a crash or restart the
rollback can therefore be resumed.

Journal location: %LOCALAPPDATA%/MiniDrive/sync-journal/<sync_id>/  (or ~/.minidrive/…),
overridable with the MINIDRIVE_JOURNAL_DIR environment variable.
"""

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CREATE_LOCAL_FILE = "CREATE_LOCAL_FILE"
OVERWRITE_LOCAL_FILE = "OVERWRITE_LOCAL_FILE"
DELETE_LOCAL_FILE = "DELETE_LOCAL_FILE"
CREATE_LOCAL_FOLDER = "CREATE_LOCAL_FOLDER"


class RollbackStepError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def journal_root() -> Path:
    override = os.environ.get("MINIDRIVE_JOURNAL_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) / "MiniDrive" if base else Path.home() / ".minidrive") / "sync-journal"


@dataclass
class LocalEntry:
    seq: int
    kind: str
    path: str                     # relative to the synchronized folder, "/"-separated
    backup: str | None = None     # file name inside the journal directory
    status: str = "PENDING"       # PENDING → APPLIED → ROLLED_BACK | ROLLBACK_FAILED
    error: str | None = None


@dataclass
class JournalData:
    synchronization_id: str
    remote_folder_id: str
    local_root: str
    created_at: str
    entries: list[LocalEntry] = field(default_factory=list)


class LocalJournal:

    def __init__(self, data: JournalData, directory: Path):
        self.data = data
        self.directory = directory

    # --- lifecycle ---------------------------------------------------------------------

    @classmethod
    def create(cls, synchronization_id: str, remote_folder_id: str, local_root: Path,
               root_dir: Path | None = None) -> "LocalJournal":
        directory = (root_dir or journal_root()) / synchronization_id
        directory.mkdir(parents=True, exist_ok=True)
        journal = cls(JournalData(
            synchronization_id=synchronization_id,
            remote_folder_id=remote_folder_id,
            local_root=str(Path(local_root).resolve()),
            created_at=datetime.now(timezone.utc).isoformat(),
        ), directory)
        journal.save()
        return journal

    @classmethod
    def list_stored(cls, root_dir: Path | None = None) -> list["LocalJournal"]:
        root = root_dir or journal_root()
        if not root.is_dir():
            return []
        result = []
        for directory in sorted(root.iterdir()):
            try:
                raw = json.loads((directory / "journal.json").read_text(encoding="utf-8"))
                raw["entries"] = [LocalEntry(**e) for e in raw.get("entries", [])]
                result.append(cls(JournalData(**raw), directory))
            except (OSError, ValueError, TypeError):
                shutil.rmtree(directory, ignore_errors=True)
        return result

    def save(self) -> None:
        temp = self.directory / "journal.json.tmp"
        temp.write_text(json.dumps(asdict(self.data), ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.directory / "journal.json")

    def discard(self) -> None:
        """Remove the journal and backups (after success or a successful rollback)."""
        shutil.rmtree(self.directory, ignore_errors=True)

    @property
    def root(self) -> Path:
        return Path(self.data.local_root)

    def local_path(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise RollbackStepError("unsafe_path")
        return path

    # --- write-ahead entries -----------------------------------------------------------------

    def _add(self, kind: str, path: str, backup_of: Path | None = None) -> LocalEntry:
        entry = LocalEntry(seq=len(self.data.entries) + 1, kind=kind, path=path)
        if backup_of is not None:
            entry.backup = f"backup-{entry.seq}"
            shutil.copy2(backup_of, self.directory / entry.backup)  # bytes + modification time
        self.data.entries.append(entry)
        self.save()
        return entry

    def applied(self, entry: LocalEntry) -> None:
        entry.status = "APPLIED"
        self.save()

    def before_write(self, relative_path: str) -> LocalEntry:
        """Before a downloaded file is written: back up the existing file or note that it is new."""
        target = self.local_path(relative_path)
        parts = relative_path.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            folder_rel = "/".join(parts[:depth])
            folder = self.local_path(folder_rel)
            if not folder.exists():
                entry = self._add(CREATE_LOCAL_FOLDER, folder_rel)
                folder.mkdir()
                self.applied(entry)
        if target.is_file():
            return self._add(OVERWRITE_LOCAL_FILE, relative_path, backup_of=target)
        return self._add(CREATE_LOCAL_FILE, relative_path)

    def before_delete(self, relative_path: str) -> LocalEntry:
        return self._add(DELETE_LOCAL_FILE, relative_path, backup_of=self.local_path(relative_path))

    # --- rollback --------------------------------------------------------------------------------

    def rollback(self) -> tuple[int, list[LocalEntry]]:
        """Reverse the local changes newest first; entries already rolled back are skipped."""
        restored = 0
        for entry in reversed(self.data.entries):
            if entry.status == "ROLLED_BACK":
                continue
            try:
                self._undo(entry)
            except RollbackStepError as exc:
                entry.status, entry.error = "ROLLBACK_FAILED", exc.code
            except PermissionError:
                entry.status, entry.error = "ROLLBACK_FAILED", "local_permission_denied"
            except OSError:
                entry.status, entry.error = "ROLLBACK_FAILED", "local_io_error"
            else:
                entry.status, entry.error = "ROLLED_BACK", None
                restored += 1
            self.save()
        return restored, [e for e in self.data.entries if e.status == "ROLLBACK_FAILED"]

    def _undo(self, entry: LocalEntry) -> None:
        path = self.local_path(entry.path)
        if entry.kind == CREATE_LOCAL_FILE:
            path.unlink(missing_ok=True)
        elif entry.kind == CREATE_LOCAL_FOLDER:
            if path.is_dir():
                if any(path.iterdir()):
                    raise RollbackStepError("folder_not_empty")  # never delete what the sync did not create
                path.rmdir()
        elif entry.kind in (OVERWRITE_LOCAL_FILE, DELETE_LOCAL_FILE):
            backup = self.directory / (entry.backup or "")
            if not entry.backup or not backup.is_file():
                raise RollbackStepError("backup_missing")
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + ".minidrive-restore")
            shutil.copy2(backup, temp)        # restores bytes and the original modification time
            os.replace(temp, path)
