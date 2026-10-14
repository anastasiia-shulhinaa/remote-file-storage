from uuid import UUID, uuid4

from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.validation import split_relative_path, validate_name
from app.repositories.file_repository import FileRepository
from app.repositories.folder_repository import FolderRepository
from app.schemas.file import FolderDto
from app.storage.storage_service import StorageService

ROOT_FOLDER_NAME = "My Drive"


class FolderService:
    """Folders of a user's Virtual Disk. The root folder (parent is null) is the disk itself."""

    def __init__(
        self,
        folder_repository: FolderRepository | None = None,
        file_repository: FileRepository | None = None,
        storage: StorageService | None = None,
    ):
        self.folders = folder_repository or FolderRepository()
        self.files = file_repository or FileRepository()
        self.storage = storage or StorageService()

    # --- ownership -------------------------------------------------------

    def get_owned_folder(self, user_id: UUID, folder_id: UUID) -> dict:
        folder = self.folders.get(folder_id)
        if folder is None:
            raise NotFoundError("Folder not found", code="folder_not_found")
        if str(folder["user_id"]) != str(user_id):
            raise ForbiddenError("You do not have access to this folder")
        return folder

    # --- queries ---------------------------------------------------------

    def ensure_root(self, user_id: UUID) -> dict:
        root = self.folders.get_root(user_id)
        if root is None:
            try:
                root = self.folders.create(user_id, ROOT_FOLDER_NAME, None)
            except Exception:
                # created concurrently (unique constraint) → read it back
                root = self.folders.get_root(user_id)
                if root is None:
                    raise
        return root

    def resolve_folder(self, user_id: UUID, folder_id: UUID | None) -> dict:
        """Owned folder by id, or the root folder when no id is given."""
        if folder_id is None:
            return self.ensure_root(user_id)
        return self.get_owned_folder(user_id, folder_id)

    def list_folders(self, user_id: UUID) -> list[FolderDto]:
        self.ensure_root(user_id)
        return [FolderDto(**f) for f in self.folders.list_by_user(user_id)]

    def list_subfolders(self, user_id: UUID, folder_id: UUID) -> list[FolderDto]:
        return [
            FolderDto(**f)
            for f in self.folders.list_by_user(user_id)
            if str(f.get("parent_folder_id")) == str(folder_id)
        ]

    def subtree_paths(self, user_id: UUID, folder_id: UUID) -> dict[str, str]:
        """{folder_id: path relative to folder_id} for the folder and all its descendants."""
        all_folders = self.folders.list_by_user(user_id)
        children: dict[str, list[dict]] = {}
        for f in all_folders:
            children.setdefault(str(f.get("parent_folder_id")), []).append(f)

        paths = {str(folder_id): ""}
        stack = [str(folder_id)]
        while stack:
            current = stack.pop()
            for child in children.get(current, []):
                child_id = str(child["id"])
                if child_id in paths:  # defensive: never loop on bad data
                    continue
                prefix = paths[current]
                paths[child_id] = f"{prefix}/{child['name']}" if prefix else child["name"]
                stack.append(child_id)
        return paths

    def breadcrumbs(self, user_id: UUID, folder_id: UUID) -> list[FolderDto]:
        by_id = {str(f["id"]): f for f in self.folders.list_by_user(user_id)}
        chain: list[FolderDto] = []
        current = by_id.get(str(folder_id))
        while current is not None and len(chain) < 100:
            chain.append(FolderDto(**current))
            parent = current.get("parent_folder_id")
            current = by_id.get(str(parent)) if parent else None
        return list(reversed(chain))

    # --- commands --------------------------------------------------------

    def create_folder(self, user_id: UUID, name: str, parent_folder_id: UUID | None) -> FolderDto:
        name = validate_name(name, "Folder")
        parent = self.resolve_folder(user_id, parent_folder_id)
        if self.folders.find_child(user_id, parent["id"], name):
            raise ConflictError(f"Folder {name!r} already exists", code="folder_exists")
        return FolderDto(**self.folders.create(user_id, name, parent["id"]))

    def ensure_path(self, user_id: UUID, base_folder: dict, relative_dir: str | None, journal=None) -> dict:
        """Return the folder at base/relative_dir, creating missing folders on the way.

        With a synchronization journal, every created folder is journaled first
        so that cancelling the synchronization can remove it again.
        """
        folder = base_folder
        for segment in split_relative_path(relative_dir):
            child = self.folders.find_child(user_id, folder["id"], segment)
            if child is None:
                folder_id = uuid4()
                entry = journal.create_folder(folder["id"], segment, folder_id) if journal else None
                try:
                    child = self.folders.create(user_id, segment, folder["id"], folder_id)
                except Exception:
                    child = self.folders.find_child(user_id, folder["id"], segment)
                    if child is None:
                        raise
                if entry is not None and str(child["id"]) == str(folder_id):
                    journal.applied(entry)
            folder = child
        return folder

    def ensure_folder_path(self, user_id: UUID, parent_folder_id: UUID | None, path: str) -> FolderDto:
        """POST /folders/path: create a nested folder path (folder upload); existing folders are reused."""
        if not split_relative_path(path):
            raise BadRequestError("Folder path is required", code="name_required")
        parent = self.resolve_folder(user_id, parent_folder_id)
        return FolderDto(**self.ensure_path(user_id, parent, path))

    def clear_folder(self, user_id: UUID, folder_id: UUID) -> dict:
        """Delete everything inside a folder (files and subfolders) but keep the folder itself.

        Also allowed for the root folder: "empty My Drive". Returns what was removed.
        """
        folder = self.get_owned_folder(user_id, folder_id)
        paths = self.subtree_paths(user_id, folder["id"])
        files = self.files.list_by_folders([UUID(fid) for fid in paths])
        # binary content first: if storage fails, metadata stays consistent
        self.storage.delete([f["storage_path"] for f in files])
        self.files.delete_many([f["id"] for f in files if str(f["folder_id"]) == str(folder["id"])])
        for child in self.list_subfolders(user_id, folder["id"]):
            self.folders.delete(child.id)  # its files and subfolders go by ON DELETE CASCADE
        return {"deleted_files": len(files), "deleted_folders": len(paths) - 1}

    def delete_folder(self, user_id: UUID, folder_id: UUID) -> None:
        folder = self.get_owned_folder(user_id, folder_id)
        if folder.get("parent_folder_id") is None:
            raise BadRequestError("The root folder of the Virtual Disk cannot be deleted", code="root_folder")

        folder_ids = list(self.subtree_paths(user_id, folder_id).keys())
        files = self.files.list_by_folders(folder_ids)
        # binary content first: if storage fails, metadata stays consistent
        self.storage.delete([f["storage_path"] for f in files])
        self.folders.delete(folder_id)
