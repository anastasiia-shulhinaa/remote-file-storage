import mimetypes
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.core.validation import (
    get_extension,
    normalize_extension,
    safe_storage_name,
    validate_name,
)
from app.repositories.file_repository import FileRepository
from app.repositories.user_repository import UserRepository
from app.schemas.file import FileDto, PreviewResponse
from app.services.folder_service import FolderService
from app.services.preview_service import PreviewService
from app.storage.storage_service import StorageService

ALLOWED_SORT = {
    "name",
    "created_at",
    "modified_at",
}
ALLOWED_ORDER = {"asc", "desc"}


# --- pure helpers (unit tested) -------------------------------------------


# one format saved under several extensions: the ".jpg" filter finds every JPEG
EXTENSION_ALIASES = {
    ".jpg": {".jpg", ".jpeg", ".jfif", ".jpe"},
}


def filter_by_extension(files: list[dict], extension: str | None) -> list[dict]:
    """Keep files with this extension: '.c' matches 'a.c' but not 'a.cpp';
    '.jpg' also matches the other JPEG extensions (.jpeg, .jfif, .jpe)."""
    extension = normalize_extension(extension)
    if extension is None:
        return list(files)
    accepted = EXTENSION_ALIASES.get(extension, {extension})
    return [f for f in files if (f.get("extension") or "").lower() in accepted]


def sort_files(files: list[dict], sort: str = "created_at", order: str = "desc") -> list[dict]:
    if sort not in ALLOWED_SORT:
        raise ValidationError(f"Cannot sort by {sort!r}; allowed: {sorted(ALLOWED_SORT)}")
    if order not in ALLOWED_ORDER:
        raise ValidationError("order must be 'asc' or 'desc'")

    def key(f: dict):
        value = f.get(sort)
        if sort == "name":
            return (value or "").lower()
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    return sorted(files, key=key, reverse=(order == "desc"))


def build_storage_path(user_id: UUID, folder_id: UUID, file_id: UUID, name: str) -> str:
    return f"{user_id}/{folder_id}/{file_id}/{safe_storage_name(name)}"


def to_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# --- service ---------------------------------------------------------------


class FileService:
    """Controller → FileService → (ownership, validation, StorageService, FileRepository)."""

    def __init__(
        self,
        file_repository: FileRepository | None = None,
        folder_service: FolderService | None = None,
        user_repository: UserRepository | None = None,
        storage: StorageService | None = None,
        preview_service: PreviewService | None = None,
    ):
        self.repository = file_repository or FileRepository()
        self.storage = storage or StorageService()
        self.folders = folder_service or FolderService(
            file_repository=self.repository, storage=self.storage
        )
        self.users = user_repository or UserRepository()
        self.previews = preview_service or PreviewService()

    # --- ownership -------------------------------------------------------

    def get_owned_file(self, user_id: UUID, file_id: UUID) -> dict:
        """current_user → folder.user_id → file.folder_id"""
        file = self.repository.get_by_id(file_id)
        if file is None:
            raise NotFoundError("File not found", code="file_not_found")
        folder = self.folders.folders.get(file["folder_id"])
        if folder is None or str(folder["user_id"]) != str(user_id):
            raise ForbiddenError("You do not have access to this file")
        return file

    # --- queries ---------------------------------------------------------

    def list_files(
        self,
        user_id: UUID,
        folder_id: UUID | None = None,
        extension: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
        recursive: bool = False,
    ) -> list[FileDto]:
        """Files of a folder; with recursive=True also the files of all its subfolders.

        Every file gets folder_path: its folder relative to the listed one
        ("" = directly in it, "labs/lab1" = in a subfolder), so a recursive
        result (e.g. "all .c files under My Drive") can show where each file is.
        """
        folder = self.folders.resolve_folder(user_id, folder_id)
        if recursive:
            paths = self.folders.subtree_paths(user_id, folder["id"])
            files = self.repository.list_by_folders([UUID(fid) for fid in paths])
        else:
            paths = {str(folder["id"]): ""}
            files = self.repository.list_by_folder(folder["id"])
        files = sort_files(filter_by_extension(files, extension), sort, order)
        return [
            dto.model_copy(update={"folder_path": paths.get(str(dto.folder_id), "")})
            for dto in self._to_dtos(files)
        ]

    def get_file(self, user_id: UUID, file_id: UUID) -> FileDto:
        return self._to_dtos([self.get_owned_file(user_id, file_id)])[0]

    def download_file(self, user_id: UUID, file_id: UUID) -> tuple[FileDto, bytes]:
        file = self.get_owned_file(user_id, file_id)
        content = self.storage.download(file["storage_path"])
        return FileDto(**file), content

    def preview_file(self, user_id: UUID, file_id: UUID) -> PreviewResponse:
        file = FileDto(**self.get_owned_file(user_id, file_id))
        # don't download content that cannot be previewed anyway (type or size)
        unavailable = self.previews.precheck(file)
        if unavailable is not None:
            return unavailable
        content = self.storage.download(file.storage_path)
        return self.previews.create_preview(file, content)

    # --- commands --------------------------------------------------------

    def upload_file(
        self,
        user_id: UUID,
        folder_id: UUID | None,
        file: UploadFile,
        relative_dir: str | None = None,
        modified_at: datetime | None = None,
        journal=None,
    ) -> FileDto:
        """Validate and store an uploaded file.

        relative_dir ("labs/lab1") places the file in subfolders of folder_id,
        creating them if needed — used by synchronization.
        modified_at keeps the local file's modification time (also for sync).
        """
        name = validate_name(file.filename)
        folder = self.folders.resolve_folder(user_id, folder_id)
        if relative_dir:
            folder = self.folders.ensure_path(user_id, folder, relative_dir, journal=journal)

        # UploadFile is spooled to memory/disk by Starlette; read synchronously
        # (this runs in the threadpool) and stop one byte past the limit.
        content = file.file.read(settings.max_file_size + 1)
        if len(content) > settings.max_file_size:
            limit_mb = settings.max_file_size // (1024 * 1024)
            raise ValidationError(f"File is larger than {limit_mb} MB", code="file_too_large")

        content_type = (
            file.content_type
            if file.content_type and file.content_type != "application/octet-stream"
            else mimetypes.guess_type(name)[0]
        )
        return self.save_file(user_id, folder, name, content, content_type, modified_at, journal=journal)

    def save_file(
        self,
        user_id: UUID,
        folder: dict,
        name: str,
        content: bytes,
        content_type: str | None = None,
        modified_at: datetime | None = None,
        journal=None,
    ) -> FileDto:
        """Create a file, or replace the content of a same-named file in the folder.

        journal: the synchronization journal when the change is part of a sync;
        the old state is backed up before anything is changed.
        """
        modified_at = to_utc(modified_at).isoformat()
        existing = self.repository.find_by_name(folder["id"], name)

        if existing is not None:
            entry = journal.overwrite_file(existing) if journal else None
            self.storage.upload(existing["storage_path"], content, content_type)
            saved = self.repository.update(existing["id"], {
                "size": len(content),
                "modified_at": modified_at,
                "modified_by": str(user_id),
            })
            if entry is not None:
                journal.applied(entry)
            return self._to_dtos([saved])[0]

        file_id = uuid4()
        storage_path = build_storage_path(user_id, folder["id"], file_id, name)
        entry = journal.create_file(folder["id"], name, file_id, storage_path) if journal else None
        self.storage.upload(storage_path, content, content_type)
        try:
            saved = self.repository.create({
                "id": str(file_id),
                "folder_id": str(folder["id"]),
                "name": name,
                "extension": get_extension(name),
                "size": len(content),
                "storage_path": storage_path,
                "modified_at": modified_at,
                "uploaded_by": str(user_id),
                "modified_by": str(user_id),
            })
        except Exception:
            # keep Storage and DB consistent: no orphan objects
            try:
                self.storage.delete(storage_path)
            except Exception:
                pass
            raise
        if entry is not None:
            journal.applied(entry)
        return self._to_dtos([saved])[0]

    def delete_file(self, user_id: UUID, file_id: UUID, journal=None) -> None:
        file = self.get_owned_file(user_id, file_id)
        entry = journal.delete_file(file) if journal else None
        # raises StorageError → metadata is not deleted
        self.storage.delete(file["storage_path"])
        self.repository.delete(file["id"])
        if entry is not None:
            journal.applied(entry)

    # --- mapping ---------------------------------------------------------

    def _to_dtos(self, files: list[dict]) -> list[FileDto]:
        user_ids = {str(f[k]) for f in files for k in ("uploaded_by", "modified_by")}
        names = self.users.get_display_names(user_ids) if user_ids else {}
        return [
            FileDto(
                **f,
                uploaded_by_name=names.get(str(f["uploaded_by"])),
                modified_by_name=names.get(str(f["modified_by"])),
            )
            for f in files
        ]
