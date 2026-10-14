from datetime import datetime, timedelta, timezone

from app.schemas.sync import ChangeKind, FileChange, SyncMode
from app.synchronization.comparator import SyncEntry

# File systems store mtime with different precision (FAT: 2 s), so timestamps
# closer than this are treated as equal.
TIMESTAMP_TOLERANCE = timedelta(seconds=2)


def _as_utc(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _is_newer(a, b) -> bool:
    a, b = _as_utc(a), _as_utc(b)
    if isinstance(a, datetime) and isinstance(b, datetime):
        return a - b > TIMESTAMP_TOLERANCE
    return a > b


def resolve_conflict(local, remote) -> ChangeKind:
    """Both sides have the file: the later modified_at wins automatically.

    The user is never asked.
    """
    if _is_newer(local.modified_at, remote.modified_at):
        return ChangeKind.UPLOAD_LOCAL

    if _is_newer(remote.modified_at, local.modified_at):
        return ChangeKind.DOWNLOAD_REMOTE

    return ChangeKind.UNCHANGED


class SyncConflictResolver:
    """Turns compared entries into concrete changes of the synchronization plan."""

    def resolve(
        self,
        entries: list[SyncEntry],
        mode: SyncMode = SyncMode.TWO_WAY,
    ) -> list[FileChange]:
        return [self.resolve_entry(entry, mode) for entry in entries]

    def resolve_entry(self, entry: SyncEntry, mode: SyncMode) -> FileChange:
        local, remote = entry.local, entry.remote

        if local is not None and remote is None:
            # local exists, remote absent
            kind = (
                ChangeKind.DELETE_LOCAL
                if mode == SyncMode.MIRROR_REMOTE
                else ChangeKind.UPLOAD_LOCAL
            )
        elif local is None and remote is not None:
            # local absent, remote exists
            kind = (
                ChangeKind.DELETE_REMOTE
                if mode == SyncMode.MIRROR_LOCAL
                else ChangeKind.DOWNLOAD_REMOTE
            )
        elif local is not None and remote is not None:
            kind = resolve_conflict(local, remote)
            if mode != SyncMode.TWO_WAY:
                # one-way modes: a file that differs always goes in the mode's direction,
                # even when the target's copy is newer (it is overwritten, never pulled back)
                differs = kind != ChangeKind.UNCHANGED or local.size != remote.size
                if not differs:
                    kind = ChangeKind.UNCHANGED
                elif mode == SyncMode.MIRROR_LOCAL:
                    kind = ChangeKind.UPLOAD_LOCAL
                else:
                    kind = ChangeKind.DOWNLOAD_REMOTE
        else:
            kind = ChangeKind.UNCHANGED

        return FileChange(
            relative_path=entry.relative_path,
            kind=kind,
            local_modified_at=local.modified_at if local else None,
            remote_modified_at=remote.modified_at if remote else None,
            remote_file_id=remote.id if remote else None,
            local_size=local.size if local else None,
            remote_size=remote.size if remote else None,
        )
