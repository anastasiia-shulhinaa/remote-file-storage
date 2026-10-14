from datetime import datetime, timezone
from pathlib import Path


def to_iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


class ScanCancelled(Exception):
    """The user cancelled while the local folder was being scanned (nothing changed yet)."""


class LocalFolderScanner:
    """Builds the local manifest: relative path, size and UTC modification time of every file.

    Only metadata is collected; file contents are sent later, when the plan says so.
    """

    def scan(self, root: Path, should_stop=lambda: False) -> list[dict]:
        root = Path(root)
        if not root.is_dir():
            raise NotADirectoryError(f"Not a folder: {root}")

        result = []
        for path in sorted(root.rglob("*")):
            if should_stop():
                raise ScanCancelled()
            # symlinks could point outside the synchronized folder
            if path.is_symlink() or not path.is_file():
                continue

            stat = path.stat()

            result.append({
                "relative_path": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "modified_at": to_iso_utc(stat.st_mtime),
            })

        return result


def scan_folder(root: Path) -> list[dict]:
    return LocalFolderScanner().scan(root)
