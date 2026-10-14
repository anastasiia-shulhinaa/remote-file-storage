from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_file_service, get_folder_service
from app.core.security import CurrentUser, get_current_user
from app.schemas.file import ClearFolderResult, FolderCreate, FolderDetails, FolderDto, FolderPathCreate
from app.services.file_service import FileService
from app.services.folder_service import FolderService

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("", response_model=list[FolderDto])
def list_folders(
    user: CurrentUser = Depends(get_current_user),
    folders: FolderService = Depends(get_folder_service),
):
    """All folders of the user's Virtual Disk (flat list; build the tree via parent_folder_id)."""
    return folders.list_folders(user.id)


@router.post("", response_model=FolderDto, status_code=201)
def create_folder(
    request: FolderCreate,
    user: CurrentUser = Depends(get_current_user),
    folders: FolderService = Depends(get_folder_service),
):
    return folders.create_folder(user.id, request.name, request.parent_folder_id)


@router.post("/path", response_model=FolderDto)
def ensure_folder_path(
    request: FolderPathCreate,
    user: CurrentUser = Depends(get_current_user),
    folders: FolderService = Depends(get_folder_service),
):
    """Create a nested folder path such as "Project/src" (folder upload). Existing folders are reused."""
    return folders.ensure_folder_path(user.id, request.parent_folder_id, request.path)


@router.get("/{folder_id}", response_model=FolderDetails)
def get_folder(
    folder_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    folders: FolderService = Depends(get_folder_service),
    files: FileService = Depends(get_file_service),
):
    folder = folders.get_owned_folder(user.id, folder_id)
    return FolderDetails(
        **folder,
        subfolders=folders.list_subfolders(user.id, folder_id),
        files=files.list_files(user.id, folder_id),
    )


@router.delete("/{folder_id}/contents", response_model=ClearFolderResult)
def clear_folder(
    folder_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    folders: FolderService = Depends(get_folder_service),
):
    """Empty a folder: all its files and subfolders are deleted, the folder itself stays."""
    return folders.clear_folder(user.id, folder_id)


@router.delete("/{folder_id}", status_code=204)
def delete_folder(
    folder_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    folders: FolderService = Depends(get_folder_service),
):
    folders.delete_folder(user.id, folder_id)
    return Response(status_code=204)
