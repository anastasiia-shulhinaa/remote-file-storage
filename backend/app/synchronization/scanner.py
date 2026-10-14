"""Remote side of synchronization: builds the remote manifest from PostgreSQL metadata.

The backend never reads the user's local disk — the Desktop Client scans the
local folder and sends its manifest in POST /sync.
"""

from uuid import UUID

from app.repositories.file_repository import FileRepository
from app.schemas.sync import RemoteFile
from app.services.folder_service import FolderService


class RemoteFolderScanner:

    def __init__(
        self,
        folder_service: FolderService | None = None,
        file_repository: FileRepository | None = None,
    ):
        self.folders = folder_service or FolderService()
        self.files = file_repository or FileRepository()

    def scan(self, user_id: UUID, folder_id: UUID) -> list[RemoteFile]:
        """All files under folder_id (recursively), with paths relative to it."""
        folder_paths = self.folders.subtree_paths(user_id, folder_id)
        files = self.files.list_by_folders([UUID(fid) for fid in folder_paths])

        result = []
        for f in files:
            prefix = folder_paths[str(f["folder_id"])]
            result.append(RemoteFile(
                id=f["id"],
                relative_path=f"{prefix}/{f['name']}" if prefix else f["name"],
                size=f["size"],
                modified_at=f["modified_at"],
            ))
        return result
