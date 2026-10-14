"""Write-ahead journal of remote changes made during one synchronization.

The file endpoints call the journal *before* changing anything:

    entry = journal.begin(...)    # 1. backup of the old bytes (Storage copy) + snapshot of the row
    ... change Storage / DB ...   # 2. the change itself
    journal.applied(entry)        # 3. mark as applied

If step 2 fails half-way the entry stays PENDING, and the rollback treats it as
"possibly applied" — every undo action is idempotent, so that is always safe.
Backups live in the same private bucket under <user_id>/.sync-backups/<sync_id>/.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.core.errors import ValidationError
from app.repositories.sync_operation_repository import SyncOperationRepository
from app.schemas.sync import OperationKind, OperationStatus
from app.storage.storage_service import StorageService


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def backup_path(user_id: UUID, synchronization_id: UUID, operation_id: UUID) -> str:
    return f"{user_id}/.sync-backups/{synchronization_id}/{operation_id}"


def json_safe(row: dict) -> dict:
    return {k: (str(v) if isinstance(v, (UUID, datetime)) else v) for k, v in row.items()}


class SyncJournal:

    def __init__(
        self,
        synchronization_id: UUID,
        user_id: UUID,
        operations: SyncOperationRepository,
        storage: StorageService,
        folder_path: Callable[[UUID], str | None],
        touch: Callable[[], None] = lambda: None,
    ):
        self.synchronization_id = synchronization_id
        self.user_id = user_id
        self.operations = operations
        self.storage = storage
        # path of a folder relative to the synchronized folder; None = outside of it
        self.folder_path = folder_path
        self.touch = touch

    # --- helpers ------------------------------------------------------------------

    def relative_path(self, folder_id: UUID, name: str | None = None) -> str:
        prefix = self.folder_path(folder_id)
        if prefix is None:
            raise ValidationError(
                "The change is outside the synchronized folder", code="outside_sync_target"
            )
        if not name:
            return prefix
        return f"{prefix}/{name}" if prefix else name

    def _begin(self, kind: OperationKind, relative_path: str, *, file: dict | None = None,
               file_id=None, folder_id=None, backup_from: str | None = None) -> dict:
        operation_id = uuid4()
        path = None
        if backup_from:
            # backup first: an entry that exists always has its backup
            path = backup_path(self.user_id, self.synchronization_id, operation_id)
            self.storage.copy(backup_from, path)
        try:
            entry = self.operations.create({
                "id": str(operation_id),
                "synchronization_id": str(self.synchronization_id),
                "user_id": str(self.user_id),
                "kind": kind.value,
                "relative_path": relative_path,
                "file_id": str(file_id) if file_id else None,
                "folder_id": str(folder_id) if folder_id else None,
                "snapshot": json_safe(file) if file else None,
                "backup_path": path,
                "status": OperationStatus.PENDING.value,
            })
        except Exception:
            if path:
                try:
                    self.storage.delete(path)
                except Exception:
                    pass
            raise
        self.touch()
        return entry

    # --- journaled changes -------------------------------------------------------------

    def create_file(self, folder_id: UUID, name: str, file_id: UUID, storage_path: str) -> dict:
        return self._begin(
            OperationKind.CREATE_REMOTE_FILE,
            self.relative_path(folder_id, name),
            file_id=file_id,
            folder_id=folder_id,
            file={"id": str(file_id), "folder_id": str(folder_id), "name": name, "storage_path": storage_path},
        )

    def overwrite_file(self, file: dict) -> dict:
        return self._begin(
            OperationKind.OVERWRITE_REMOTE_FILE,
            self.relative_path(file["folder_id"], file["name"]),
            file=file,
            file_id=file["id"],
            folder_id=file["folder_id"],
            backup_from=file["storage_path"],
        )

    def delete_file(self, file: dict) -> dict:
        return self._begin(
            OperationKind.DELETE_REMOTE_FILE,
            self.relative_path(file["folder_id"], file["name"]),
            file=file,
            file_id=file["id"],
            folder_id=file["folder_id"],
            backup_from=file["storage_path"],
        )

    def create_folder(self, parent_id: UUID, name: str, folder_id: UUID) -> dict:
        return self._begin(
            OperationKind.CREATE_REMOTE_FOLDER,
            self.relative_path(parent_id, name),
            folder_id=folder_id,
        )

    def applied(self, entry: dict) -> None:
        self.operations.update(entry["id"], {"status": OperationStatus.APPLIED.value, "updated_at": now_iso()})
