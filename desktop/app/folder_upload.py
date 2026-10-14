"""Upload of files and whole folders (drag-and-drop from Explorer or "Add folder").

The relative structure is preserved: Project/src/main.py is uploaded into the remote
folders Project → src (created by the backend). Nothing is skipped silently: every
file that cannot be uploaded is reported with a reason code.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class UploadProblem(Exception):
    """A client-side reason why a file was not uploaded (code → translated message)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class UploadItem:
    path: Path
    relative: str        # "Project/src/main.py" ("/"-separated); just the name for single files


@dataclass
class UploadSelection:
    items: list[UploadItem] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)     # every directory (relative), incl. empty ones
    roots: list[str] = field(default_factory=list)
    problems: list[tuple[str, BaseException]] = field(default_factory=list)

    @property
    def is_folder(self) -> bool:
        return bool(self.dirs)


@dataclass
class UploadOutcome:
    uploaded: int = 0
    folders_created: int = 0
    failures: list[tuple[str, BaseException]] = field(default_factory=list)


def collect_paths(paths: list[Path]) -> UploadSelection:
    """Files and folders dropped onto the window (local paths)."""
    selection = UploadSelection()
    for path in paths:
        path = Path(path)
        selection.roots.append(path.name)
        if path.is_symlink():
            selection.problems.append((path.name, UploadProblem("symlink")))
        elif path.is_file():
            selection.items.append(UploadItem(path, path.name))
        elif path.is_dir():
            _walk(path, path.name, selection)
    return selection


def _walk(directory: Path, relative: str, selection: UploadSelection) -> None:
    selection.dirs.append(relative)
    try:
        entries = sorted(os.scandir(directory), key=lambda e: e.name.lower())
    except OSError as exc:
        selection.problems.append((relative + "/", exc))
        return
    for entry in entries:
        child_relative = f"{relative}/{entry.name}"
        if entry.is_symlink():
            # a link could point outside the chosen folder
            selection.problems.append((child_relative, UploadProblem("symlink")))
        elif entry.is_dir(follow_symlinks=False):
            _walk(Path(entry.path), child_relative, selection)
        elif entry.is_file(follow_symlinks=False):
            selection.items.append(UploadItem(Path(entry.path), child_relative))


def upload_selection(
    api,
    selection: UploadSelection,
    folder_id: str,
    on_progress: Callable[[int, int, str | None], None] = lambda done, total, current: None,
) -> UploadOutcome:
    outcome = UploadOutcome(failures=list(selection.problems))
    total = len(selection.items)

    # folders without files are created explicitly (uploads create the others)
    empty_dirs = [
        d for d in selection.dirs
        if not any(i.relative.startswith(d + "/") for i in selection.items)
        and not any(o.startswith(d + "/") for o in selection.dirs)
    ]
    for directory in empty_dirs:
        try:
            api.ensure_folder_path(directory, folder_id)
            outcome.folders_created += 1
        except Exception as exc:
            outcome.failures.append((directory + "/", exc))

    for index, item in enumerate(selection.items):
        on_progress(index, total, item.relative)
        try:
            if item.path.stat().st_size > MAX_UPLOAD_BYTES:
                raise UploadProblem("file_too_large")
            relative_dir = item.relative.rpartition("/")[0]
            api.upload_file(item.path, folder_id=folder_id, relative_dir=relative_dir or None)
            outcome.uploaded += 1
        except Exception as exc:
            outcome.failures.append((item.relative, exc))
    on_progress(total, total, None)
    return outcome
