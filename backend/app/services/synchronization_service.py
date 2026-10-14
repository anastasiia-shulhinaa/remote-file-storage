import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.schema_check import is_missing_schema
from app.repositories.sync_operation_repository import SyncOperationRepository
from app.repositories.synchronization_repository import SynchronizationRepository
from app.schemas.sync import (
    ACTIVE_STATUSES,
    FINISHED_STATUSES,
    REPORTABLE_FROM,
    ChangeKind,
    FinishRollbackRequest,
    LocalFileEntry,
    OperationStatus,
    SyncMode,
    SyncOperationDto,
    SynchronizationDetails,
    SynchronizationDto,
    SynchronizationPlan,
    SynchronizationUpdate,
    SyncStatus,
)
from app.services.folder_service import FolderService
from app.synchronization.comparator import FileComparator
from app.synchronization.conflict_resolver import SyncConflictResolver
from app.synchronization.journal import SyncJournal, now_iso
from app.synchronization.rollback import RemoteRollback
from app.synchronization.scanner import RemoteFolderScanner

logger = logging.getLogger("nastusha")

# a PENDING/RUNNING session without any activity for this long was abandoned
# (client closed or crashed): it no longer blocks its target folder
LEASE = timedelta(minutes=10)

UNDONE_REMOTE = {OperationStatus.ROLLED_BACK.value, OperationStatus.COMMITTED.value}


def _parse(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class SynchronizationService:
    """Synchronization sessions.

    Planning: compares a local manifest with remote metadata and returns a plan.
    Execution: done by the client (desktop or web) through the regular file
    endpoints; remote changes made with a synchronization_id are journaled.
    Cancellation: the session is moved through CANCEL_REQUESTED → ROLLING_BACK →
    CANCELLED / ROLLBACK_FAILED; the server reverses the remote changes, the
    client reverses its local ones (the server never touches the local disk).
    """

    def __init__(
        self,
        folder_service: FolderService | None = None,
        remote_scanner: RemoteFolderScanner | None = None,
        comparator: FileComparator | None = None,
        conflict_resolver: SyncConflictResolver | None = None,
        history: SynchronizationRepository | None = None,
        operations: SyncOperationRepository | None = None,
    ):
        self.folders = folder_service or FolderService()
        self.remote_scanner = remote_scanner or RemoteFolderScanner(folder_service=self.folders)
        self.comparator = comparator or FileComparator()
        self.conflict_resolver = conflict_resolver or SyncConflictResolver()
        self.history = history or SynchronizationRepository()
        self.operations = operations or SyncOperationRepository()

    @property
    def rollback_engine(self) -> RemoteRollback:
        return RemoteRollback(self.operations, self.folders.files, self.folders.folders, self.folders.storage)

    # --- planning ---------------------------------------------------------------------

    def run(
        self,
        user_id: UUID,
        folder_id: UUID,
        manifest: list[LocalFileEntry],
        mode: SyncMode = SyncMode.TWO_WAY,
        client: str = "api",
        device: str | None = None,
    ) -> SynchronizationPlan:
        folder = self.folders.get_owned_folder(user_id, folder_id)
        self._ensure_target_free(user_id, folder["id"])

        remote_files = self.remote_scanner.scan(user_id, folder["id"])

        entries = self.comparator.compare(manifest, remote_files)

        changes = self.conflict_resolver.resolve(entries, mode)

        plan = SynchronizationPlan(
            remote_folder_id=folder["id"],
            mode=mode,
            changes=changes,
        )
        plan.synchronization_id = self._start_history(user_id, plan, client, device)
        return plan

    def _start_history(self, user_id: UUID, plan: SynchronizationPlan, client: str,
                       device: str | None = None) -> UUID:
        """PENDING session for the new plan; COMPLETED at once when there is nothing to do.

        Every plan has a session: without it the run could not be cancelled and rolled
        back, so a history failure refuses the synchronization with a clear code.
        """
        nothing_to_do = plan.actionable == 0
        now = now_iso()
        try:
            row = self.history.create({
                "user_id": str(user_id),
                "remote_folder_id": str(plan.remote_folder_id),
                "client": client,
                "device": device,
                "mode": plan.mode.value,
                "status": (SyncStatus.COMPLETED if nothing_to_do else SyncStatus.PENDING).value,
                "planned_changes": plan.actionable,
                "unchanged": plan.count(ChangeKind.UNCHANGED),
                "started_at": now,
                "updated_at": now,
                "finished_at": now if nothing_to_do else None,
            })
        except ConflictError:
            raise
        except Exception as exc:
            if "uq_synchronizations_active_target" in str(exc):
                raise ConflictError(
                    "Another synchronization of this folder is in progress", code="sync_in_progress"
                ) from exc
            raise self._history_error(exc) from exc
        return UUID(str(row["id"]))

    @staticmethod
    def _history_error(exc: Exception) -> ServiceUnavailableError:
        if is_missing_schema(exc):
            logger.error("Synchronization tables are outdated (run supabase/migrations/003_sync_rollback.sql): %s", exc)
            return ServiceUnavailableError("Database schema is outdated", code="schema_outdated")
        logger.error("Synchronization history unavailable: %s", exc)
        return ServiceUnavailableError("Synchronization history is unavailable", code="history_unavailable")

    # --- concurrency: one active session per target (incl. parent/child folders) ------------

    def _ensure_target_free(self, user_id: UUID, folder_id: UUID) -> None:
        try:
            active = self.history.list_with_status(user_id, [s.value for s in ACTIVE_STATUSES])
        except Exception as exc:
            raise self._history_error(exc) from exc
        if not active:
            return
        target_subtree = set(self.folders.subtree_paths(user_id, folder_id))
        for session in active:
            other = session.get("remote_folder_id")
            if not other:
                continue
            overlaps = str(other) in target_subtree or str(folder_id) in self.folders.subtree_paths(user_id, other)
            if not overlaps:
                continue
            if self._abandon_if_stale(session):
                continue
            raise ConflictError(
                "Another synchronization of this folder is in progress",
                code="sync_in_progress",
                extra={"synchronization_id": str(session["id"]), "status": session["status"]},
            )

    def _abandon_if_stale(self, session: dict) -> bool:
        """A PENDING/RUNNING session nobody touched for LEASE is closed as FAILED (interrupted).

        Cancellation and rollback sessions are never abandoned automatically: they keep
        the lock until the rollback is finished (it can be resumed after a reconnect).
        """
        if session["status"] not in (SyncStatus.PENDING.value, SyncStatus.RUNNING.value):
            return False
        last = _parse(session.get("updated_at")) or _parse(session.get("started_at"))
        if last is None or datetime.now(timezone.utc) - last < LEASE:
            return False
        try:
            closed = self.history.update_if_status(
                session["id"],
                [SyncStatus.PENDING.value, SyncStatus.RUNNING.value],
                {"status": SyncStatus.FAILED.value, "error": "interrupted", "finished_at": now_iso(),
                 "updated_at": now_iso()},
            )
        except Exception as exc:
            raise self._history_error(exc) from exc
        if closed is not None:
            self._commit(session["id"])
        return True

    # --- session access -------------------------------------------------------------------

    def get_owned(self, user_id: UUID, synchronization_id: UUID) -> dict:
        row = self._history_call(self.history.get, synchronization_id)
        if row is None:
            raise NotFoundError("Synchronization not found", code="synchronization_not_found")
        if str(row["user_id"]) != str(user_id):
            raise ForbiddenError("You do not have access to this synchronization")
        return row

    @staticmethod
    def _state_error(row: dict) -> ConflictError:
        status = SyncStatus(row["status"])
        if status in (SyncStatus.CANCEL_REQUESTED, SyncStatus.ROLLING_BACK, SyncStatus.ROLLBACK_FAILED):
            return ConflictError("The synchronization is being cancelled", code="sync_cancelled",
                                 extra={"status": status.value})
        return ConflictError(f"Synchronization is already {status.value}", code="synchronization_finished",
                             extra={"status": status.value})

    def open_journal(self, user_id: UUID, synchronization_id: UUID) -> SyncJournal:
        """Journal for a remote change made as part of a running synchronization.

        After a cancel request no further changes are accepted (409 sync_cancelled).
        """
        row = self.get_owned(user_id, synchronization_id)
        if row["status"] == SyncStatus.PENDING.value:
            row = self.history.update_if_status(
                synchronization_id, [SyncStatus.PENDING.value],
                {"status": SyncStatus.RUNNING.value, "updated_at": now_iso()},
            ) or self.get_owned(user_id, synchronization_id)
        if row["status"] != SyncStatus.RUNNING.value:
            raise self._state_error(row)

        target = row["remote_folder_id"]

        def folder_path(folder_id) -> str | None:
            return self.folders.subtree_paths(user_id, target).get(str(folder_id))

        def touch() -> None:
            try:
                self.history.update(synchronization_id, {"updated_at": now_iso()})
            except Exception:
                pass

        return SyncJournal(synchronization_id, user_id, self.operations, self.folders.storage, folder_path, touch)

    # --- progress / normal completion ------------------------------------------------------------

    def report(
        self,
        user_id: UUID,
        synchronization_id: UUID,
        update: SynchronizationUpdate,
    ) -> SynchronizationDto:
        """Progress (RUNNING) or the final result (COMPLETED / FAILED) of an executed plan."""
        row = self.get_owned(user_id, synchronization_id)
        if SyncStatus(row["status"]) not in REPORTABLE_FROM:
            raise self._state_error(row)

        data = update.model_dump(mode="json")
        data["updated_at"] = now_iso()
        finished = update.status in (SyncStatus.COMPLETED, SyncStatus.FAILED)
        if finished:
            data["finished_at"] = now_iso()
        saved = self._history_call(
            self.history.update_if_status,
            synchronization_id, [s.value for s in REPORTABLE_FROM], data,
        )
        if saved is None:  # cancelled meanwhile
            raise self._state_error(self.get_owned(user_id, synchronization_id))
        if finished:
            self._commit(synchronization_id)
        return SynchronizationDto(**saved)

    def _commit(self, synchronization_id) -> None:
        """Finished normally: the journal is no longer needed, remove its backups."""
        try:
            entries = self.operations.list_by_synchronization(synchronization_id)
        except Exception as exc:
            logger.warning("Journal cleanup skipped: %s", exc)
            return
        backups = [e["backup_path"] for e in entries if e.get("backup_path")]
        if backups:
            try:
                self.folders.storage.delete(backups)
            except Exception:
                logger.warning("Backups of synchronization %s could not be removed", synchronization_id)
        for entry in entries:
            if entry["status"] != OperationStatus.COMMITTED.value:
                self.operations.update(entry["id"], {"status": OperationStatus.COMMITTED.value, "updated_at": now_iso()})

    # --- cancellation and rollback -------------------------------------------------------------

    def cancel(self, user_id: UUID, synchronization_id: UUID) -> SynchronizationDto:
        """Idempotent: RUNNING/PENDING → CANCEL_REQUESTED; later cancel requests change nothing."""
        row = self.get_owned(user_id, synchronization_id)
        status = SyncStatus(row["status"])
        if status in (SyncStatus.PENDING, SyncStatus.RUNNING):
            moved = self.history.update_if_status(
                synchronization_id, [SyncStatus.PENDING.value, SyncStatus.RUNNING.value],
                {"status": SyncStatus.CANCEL_REQUESTED.value, "updated_at": now_iso()},
            )
            row = moved or self.get_owned(user_id, synchronization_id)
            status = SyncStatus(row["status"])
        if status in (SyncStatus.COMPLETED, SyncStatus.FAILED):
            raise self._state_error(row)
        return SynchronizationDto(**row)

    def rollback(self, user_id: UUID, synchronization_id: UUID) -> SynchronizationDetails:
        """Reverse the remote changes. Safe to call again (resume after a reconnect / retry)."""
        row = self.get_owned(user_id, synchronization_id)
        status = SyncStatus(row["status"])
        if status == SyncStatus.CANCELLED:
            return self.details(user_id, synchronization_id)
        if status in (SyncStatus.PENDING, SyncStatus.RUNNING):
            raise ConflictError("Cancel the synchronization first", code="not_cancelled")
        if status in (SyncStatus.COMPLETED, SyncStatus.FAILED):
            raise self._state_error(row)
        if status in (SyncStatus.CANCEL_REQUESTED, SyncStatus.ROLLBACK_FAILED):
            self.history.update_if_status(
                synchronization_id, [status.value],
                {"status": SyncStatus.ROLLING_BACK.value, "updated_at": now_iso()},
            )
        self.rollback_engine.run(self.operations.list_by_synchronization(synchronization_id))
        return self.details(user_id, synchronization_id)

    def finish_rollback(
        self,
        user_id: UUID,
        synchronization_id: UUID,
        request: FinishRollbackRequest,
    ) -> SynchronizationDetails:
        """Final status after both halves of the rollback: CANCELLED or ROLLBACK_FAILED."""
        row = self.get_owned(user_id, synchronization_id)
        status = SyncStatus(row["status"])
        if status == SyncStatus.CANCELLED:
            return self.details(user_id, synchronization_id)
        if status != SyncStatus.ROLLING_BACK:
            raise ConflictError("The rollback has not been started", code="rollback_not_started")

        entries = self.operations.list_by_synchronization(synchronization_id)
        remote_failures = [
            {"relative_path": e.get("relative_path"), "operation": e["kind"], "code": e.get("error") or "not_restored"}
            for e in entries if e["status"] not in UNDONE_REMOTE
        ]
        local_failures = [f.model_dump() for f in request.local_failures]
        final = SyncStatus.ROLLBACK_FAILED if remote_failures or local_failures else SyncStatus.CANCELLED
        report = {
            "remote_restored": sum(1 for e in entries if e["status"] == OperationStatus.ROLLED_BACK.value),
            "local_restored": request.local_restored,
            "remote_failures": remote_failures,
            "local_failures": local_failures,
        }
        counts = request.counts.model_dump() if request.counts else {}
        self.history.update_if_status(synchronization_id, [SyncStatus.ROLLING_BACK.value], {
            **counts,
            "status": final.value,
            "rollback_report": report,
            "error": None if final == SyncStatus.CANCELLED else "rollback_failed",
            "finished_at": now_iso(),
            "updated_at": now_iso(),
        })
        return self.details(user_id, synchronization_id)

    # --- queries ------------------------------------------------------------------------------

    def details(self, user_id: UUID, synchronization_id: UUID) -> SynchronizationDetails:
        row = self.get_owned(user_id, synchronization_id)
        try:
            entries = self.operations.list_by_synchronization(synchronization_id)
        except Exception as exc:
            logger.warning("Journal unavailable: %s", exc)
            entries = []
        return SynchronizationDetails(
            **row,
            operations=[SyncOperationDto(**e) for e in entries],
        )

    def list_history(self, user_id: UUID, limit: int = 20) -> list[SynchronizationDto]:
        rows = self._history_call(self.history.list_by_user, user_id, limit)
        return [SynchronizationDto(**row) for row in rows]

    @staticmethod
    def _history_call(operation, *args):
        """Database failures of the history (e.g. the synchronizations table is missing
        because supabase/schema.sql was not applied) become a clear 503, not a raw 500."""
        try:
            return operation(*args)
        except Exception as exc:
            raise SynchronizationService._history_error(exc) from exc
