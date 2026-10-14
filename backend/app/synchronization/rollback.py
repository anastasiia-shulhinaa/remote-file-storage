"""Reverses the journaled remote changes of one synchronization.

Entries are undone newest first. Each entry is claimed with a compare-and-set
(PENDING / APPLIED / ROLLBACK_FAILED → ROLLING_BACK), so concurrent or repeated
rollback requests never reverse the same change twice. Every undo action is
idempotent, so an entry interrupted half-way can safely be retried.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.core.errors import AppError
from app.repositories.file_repository import FileRepository
from app.repositories.folder_repository import FolderRepository
from app.repositories.sync_operation_repository import SyncOperationRepository
from app.schemas.sync import OperationKind, OperationStatus
from app.storage.storage_service import StorageService
from app.synchronization.journal import now_iso

logger = logging.getLogger("nastusha")

CLAIMABLE = [OperationStatus.PENDING.value, OperationStatus.APPLIED.value, OperationStatus.ROLLBACK_FAILED.value]
# an entry left in ROLLING_BACK by a crashed request may be claimed again after this time
STALE_CLAIM = timedelta(minutes=5)

FILE_FIELDS = (
    "id", "folder_id", "name", "extension", "size", "storage_path",
    "created_at", "modified_at", "uploaded_by", "modified_by",
)


class RollbackStepError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RemoteRollback:

    def __init__(
        self,
        operations: SyncOperationRepository,
        files: FileRepository,
        folders: FolderRepository,
        storage: StorageService,
    ):
        self.operations = operations
        self.files = files
        self.folders = folders
        self.storage = storage

    def run(self, entries: list[dict]) -> None:
        for entry in sorted(entries, key=lambda e: e["seq"], reverse=True):
            if entry["status"] in (OperationStatus.ROLLED_BACK.value, OperationStatus.COMMITTED.value):
                continue
            claimed = self._claim(entry)
            if claimed is None:
                continue  # another request is reversing it, or already did
            try:
                self._undo(claimed)
            except RollbackStepError as exc:
                self._mark(claimed, OperationStatus.ROLLBACK_FAILED, exc.code)
                continue
            except AppError as exc:
                self._mark(claimed, OperationStatus.ROLLBACK_FAILED, exc.code)
                continue
            except Exception as exc:
                logger.error("Rollback of %s failed: %s", claimed["id"], exc)
                self._mark(claimed, OperationStatus.ROLLBACK_FAILED, "rollback_error")
                continue
            self._mark(claimed, OperationStatus.ROLLED_BACK, None)
            if claimed.get("backup_path"):
                try:
                    self.storage.delete(claimed["backup_path"])
                except Exception:
                    logger.warning("Backup %s could not be removed", claimed["backup_path"])

    # --- claiming -------------------------------------------------------------------

    def _claim(self, entry: dict) -> dict | None:
        data = {"status": OperationStatus.ROLLING_BACK.value, "updated_at": now_iso()}
        if entry["status"] == OperationStatus.ROLLING_BACK.value:
            cutoff = (datetime.now(timezone.utc) - STALE_CLAIM).isoformat()
            return self.operations.update_if_status(
                entry["id"], [OperationStatus.ROLLING_BACK.value], data, updated_before=cutoff
            )
        return self.operations.update_if_status(entry["id"], CLAIMABLE, data)

    def _mark(self, entry: dict, status: OperationStatus, error: str | None) -> None:
        self.operations.update(entry["id"], {"status": status.value, "error": error, "updated_at": now_iso()})

    # --- undo actions (all idempotent) -----------------------------------------------------

    def _undo(self, entry: dict) -> None:
        kind = OperationKind(entry["kind"])
        if kind == OperationKind.CREATE_REMOTE_FILE:
            self._undo_create_file(entry)
        elif kind == OperationKind.OVERWRITE_REMOTE_FILE:
            self._restore_file(entry, recreate_row=False)
        elif kind == OperationKind.DELETE_REMOTE_FILE:
            self._restore_file(entry, recreate_row=True)
        elif kind == OperationKind.CREATE_REMOTE_FOLDER:
            self._undo_create_folder(entry)

    def _undo_create_file(self, entry: dict) -> None:
        row = self.files.get_by_id(entry["file_id"])
        storage_path = (row or {}).get("storage_path") or (entry.get("snapshot") or {}).get("storage_path")
        if storage_path:
            self.storage.delete(storage_path)  # also removes bytes of a half-finished upload
        if row is not None:
            self.files.delete(entry["file_id"])

    def _restore_file(self, entry: dict, recreate_row: bool) -> None:
        snapshot = entry.get("snapshot") or {}
        if not entry.get("backup_path") or not snapshot:
            raise RollbackStepError("backup_missing")
        content = self.storage.download(entry["backup_path"])
        self.storage.upload(snapshot["storage_path"], content, None)

        row = self.files.get_by_id(snapshot["id"])
        if row is None:
            if self.folders.get(snapshot["folder_id"]) is None:
                raise RollbackStepError("folder_missing")
            occupant = self.files.find_by_name(snapshot["folder_id"], snapshot["name"])
            if occupant is not None:
                # another file took this name after the sync started
                raise RollbackStepError("name_conflict")
            self.files.create({k: snapshot[k] for k in FILE_FIELDS if k in snapshot})
        else:
            self.files.update(snapshot["id"], {
                "size": snapshot["size"],
                "modified_at": snapshot["modified_at"],
                "modified_by": snapshot["modified_by"],
            })

    def _undo_create_folder(self, entry: dict) -> None:
        folder = self.folders.get(entry["folder_id"])
        if folder is None:
            return
        has_subfolders = any(
            str(f.get("parent_folder_id")) == str(entry["folder_id"])
            for f in self.folders.list_by_user(folder["user_id"])
        )
        if has_subfolders or self.files.list_by_folder(entry["folder_id"]):
            # something else was put into it: never delete data the sync did not create
            raise RollbackStepError("folder_not_empty")
        self.folders.delete(entry["folder_id"])
