from dataclasses import dataclass

from app.core.errors import ValidationError
from app.core.validation import split_relative_path
from app.schemas.sync import LocalFileEntry, RemoteFile


@dataclass
class SyncEntry:
    """One relative path with its local and/or remote version."""

    relative_path: str
    local: LocalFileEntry | None = None
    remote: RemoteFile | None = None


def normalize_path(path: str) -> str:
    return "/".join(split_relative_path(path))


class FileComparator:
    """Matches the local manifest with remote metadata by relative path."""

    def compare(
        self,
        manifest: list[LocalFileEntry],
        remote_files: list[RemoteFile],
    ) -> list[SyncEntry]:
        entries: dict[str, SyncEntry] = {}

        for local in manifest:
            path = normalize_path(local.relative_path)
            if not path:
                raise ValidationError("Empty relative_path in manifest", code="invalid_manifest")
            if path in entries:
                raise ValidationError(f"Duplicate path in manifest: {path}", code="invalid_manifest")
            entries[path] = SyncEntry(
                relative_path=path,
                local=local.model_copy(update={"relative_path": path}),
            )

        for remote in remote_files:
            path = remote.relative_path
            entry = entries.setdefault(path, SyncEntry(relative_path=path))
            entry.remote = remote

        return sorted(entries.values(), key=lambda e: e.relative_path)
