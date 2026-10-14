from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ChangeKind(str, Enum):
    UPLOAD_LOCAL = "UPLOAD_LOCAL"
    DOWNLOAD_REMOTE = "DOWNLOAD_REMOTE"
    DELETE_REMOTE = "DELETE_REMOTE"
    DELETE_LOCAL = "DELETE_LOCAL"
    UNCHANGED = "UNCHANGED"


class SyncMode(str, Enum):
    # both sides keep everything; the newer version of a file wins
    TWO_WAY = "two_way"
    # local folder is the source of truth: files missing locally are deleted remotely
    MIRROR_LOCAL = "mirror_local"
    # remote folder is the source of truth: files missing remotely are deleted locally
    MIRROR_REMOTE = "mirror_remote"


class LocalFileEntry(BaseModel):
    relative_path: str = Field(min_length=1, max_length=1024)
    size: int = Field(ge=0)
    modified_at: datetime


class RemoteFile(BaseModel):
    """A remote file with its path relative to the synchronized remote folder."""

    id: UUID
    relative_path: str
    size: int
    modified_at: datetime


class SyncRequest(BaseModel):
    remote_folder_id: UUID
    manifest: list[LocalFileEntry] = Field(max_length=10_000)
    mode: SyncMode = SyncMode.TWO_WAY
    # which client executes the plan; stored in the history only
    client: Literal["desktop", "web", "api"] = "api"
    # the computer (desktop host name) or browser ("Edge · Windows") — shown in the history
    device: str | None = Field(default=None, max_length=100)

    @field_validator("device")
    @classmethod
    def _clean_device(cls, value):
        if value is None:
            return None
        value = "".join(ch for ch in value if ch.isprintable()).strip()
        return value[:100] or None


class FileChange(BaseModel):
    relative_path: str
    kind: ChangeKind
    local_modified_at: datetime | None = None
    remote_modified_at: datetime | None = None
    remote_file_id: UUID | None = None
    local_size: int | None = None
    remote_size: int | None = None


class SynchronizationPlan(BaseModel):
    remote_folder_id: UUID
    mode: SyncMode
    changes: list[FileChange]
    # persistent history record; the client reports the execution result to it.
    # None only if the history could not be written (the plan is still valid).
    synchronization_id: UUID | None = None

    def count(self, kind: ChangeKind) -> int:
        return sum(1 for c in self.changes if c.kind == kind)

    @property
    def actionable(self) -> int:
        return sum(1 for c in self.changes if c.kind != ChangeKind.UNCHANGED)


# --- synchronization session (persistent summary + state machine) ------------------


class SyncStatus(str, Enum):
    PENDING = "PENDING"                    # plan created, client has not started executing it
    RUNNING = "RUNNING"                    # client is executing the plan
    CANCEL_REQUESTED = "CANCEL_REQUESTED"  # cancel pressed: no new changes are accepted
    ROLLING_BACK = "ROLLING_BACK"          # changes made by this sync are being reversed
    CANCELLED = "CANCELLED"                # rolled back: local and remote state as before the sync
    ROLLBACK_FAILED = "ROLLBACK_FAILED"    # some changes could not be reversed (see rollback_report)
    COMPLETED = "COMPLETED"                # every change succeeded
    FAILED = "FAILED"                      # at least one change failed, or the run was interrupted


# statuses that hold the lock on the target folder (no second sync, no other rollback)
ACTIVE_STATUSES = {
    SyncStatus.PENDING,
    SyncStatus.RUNNING,
    SyncStatus.CANCEL_REQUESTED,
    SyncStatus.ROLLING_BACK,
}
# terminal statuses (ROLLBACK_FAILED is not terminal: the rollback may be retried)
FINISHED_STATUSES = {SyncStatus.COMPLETED, SyncStatus.FAILED, SyncStatus.CANCELLED}
# what a client may report with PATCH /synchronizations/{id} while executing a plan
REPORTABLE_FROM = {SyncStatus.PENDING, SyncStatus.RUNNING}


class SyncCounts(BaseModel):
    uploaded: int = Field(default=0, ge=0)
    downloaded: int = Field(default=0, ge=0)
    deleted_local: int = Field(default=0, ge=0)
    deleted_remote: int = Field(default=0, ge=0)
    unchanged: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class SynchronizationUpdate(SyncCounts):
    """Progress / execution result reported by the client that runs the plan.

    Cancellation and rollback have their own endpoints, so only these three are allowed.
    """

    status: Literal[SyncStatus.RUNNING, SyncStatus.COMPLETED, SyncStatus.FAILED]
    error: str | None = Field(default=None, max_length=2000)


class SynchronizationDto(SyncCounts):
    id: UUID
    user_id: UUID
    remote_folder_id: UUID | None = None
    client: str
    device: str | None = None
    mode: SyncMode
    status: SyncStatus
    planned_changes: int = 0
    error: str | None = None
    rollback_report: dict | None = None
    started_at: datetime
    updated_at: datetime | None = None
    finished_at: datetime | None = None


# --- operation journal (remote side) ---------------------------------------------------


class OperationKind(str, Enum):
    """Remote changes made through the file endpoints during a synchronization."""

    CREATE_REMOTE_FILE = "CREATE_REMOTE_FILE"        # rollback: delete the new file
    OVERWRITE_REMOTE_FILE = "OVERWRITE_REMOTE_FILE"  # rollback: restore old bytes + metadata
    DELETE_REMOTE_FILE = "DELETE_REMOTE_FILE"        # rollback: recreate from the snapshot
    CREATE_REMOTE_FOLDER = "CREATE_REMOTE_FOLDER"    # rollback: remove the (empty) folder


class OperationStatus(str, Enum):
    PENDING = "PENDING"                  # written before the change: it may or may not be applied
    APPLIED = "APPLIED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    COMMITTED = "COMMITTED"              # the sync finished normally; backup removed


class SyncOperationDto(BaseModel):
    id: UUID
    seq: int
    kind: OperationKind
    relative_path: str | None = None
    status: OperationStatus
    error: str | None = None


class SynchronizationDetails(SynchronizationDto):
    operations: list[SyncOperationDto] = []


class LocalRollbackFailure(BaseModel):
    relative_path: str = Field(max_length=1024)
    operation: str = Field(max_length=64)
    code: str = Field(max_length=64)


class FinishRollbackRequest(BaseModel):
    """Result of the client-side (local filesystem) part of the rollback."""

    local_restored: int = Field(default=0, ge=0)
    local_failures: list[LocalRollbackFailure] = Field(default=[], max_length=10_000)
    # what had been done before the cancel (kept in the history; all of it was rolled back)
    counts: SyncCounts | None = None
