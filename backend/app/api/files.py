from datetime import datetime
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile

from app.api.deps import get_file_service, get_sync_service
from app.core.security import CurrentUser, get_current_user
from app.schemas.file import FileDto
from app.services.file_service import FileService
from app.services.synchronization_service import SynchronizationService

router = APIRouter(prefix="/files", tags=["files"])


def content_disposition(name: str, disposition: str = "attachment") -> str:
    """RFC 6266 header that also works for non-ASCII (e.g. Cyrillic) file names."""
    fallback = name.encode("ascii", "ignore").decode().replace('"', "").strip() or "download"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"


@router.get("", response_model=list[FileDto])
def list_files(
    folder_id: UUID | None = Query(None, description="Folder; the root folder when omitted"),
    extension: str | None = Query(None, description="Exact extension filter, e.g. .c or .jpg"),
    sort: str = Query("created_at", description="name | created_at | modified_at"),
    order: str = Query("desc", description="asc | desc"),
    recursive: bool = Query(False, description="Also list the files of all subfolders (each with folder_path)"),
    user: CurrentUser = Depends(get_current_user),
    files: FileService = Depends(get_file_service),
):
    return files.list_files(user.id, folder_id, extension, sort, order, recursive)


@router.post("", response_model=FileDto, status_code=201)
def upload_file(
    file: UploadFile = File(...),
    folder_id: UUID | None = Form(None),
    relative_dir: str | None = Form(None),
    modified_at: datetime | None = Form(None),
    synchronization_id: UUID | None = Form(None, description="Journal the change for rollback"),
    user: CurrentUser = Depends(get_current_user),
    files: FileService = Depends(get_file_service),
    sync: SynchronizationService = Depends(get_sync_service),
):
    journal = sync.open_journal(user.id, synchronization_id) if synchronization_id else None
    return files.upload_file(
        user_id=user.id,
        folder_id=folder_id,
        file=file,
        relative_dir=relative_dir,
        modified_at=modified_at,
        journal=journal,
    )


@router.get("/{file_id}", response_model=FileDto)
def get_file(
    file_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    files: FileService = Depends(get_file_service),
):
    return files.get_file(user.id, file_id)


@router.get("/{file_id}/content")
def download_file(
    file_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    files: FileService = Depends(get_file_service),
):
    file, content = files.download_file(user.id, file_id)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(file.name),
            "X-File-Modified-At": file.modified_at.isoformat(),
        },
    )


@router.delete("/{file_id}", status_code=204)
def delete_file(
    file_id: UUID,
    synchronization_id: UUID | None = Query(None, description="Journal the change for rollback"),
    user: CurrentUser = Depends(get_current_user),
    files: FileService = Depends(get_file_service),
    sync: SynchronizationService = Depends(get_sync_service),
):
    journal = sync.open_journal(user.id, synchronization_id) if synchronization_id else None
    files.delete_file(user.id, file_id, journal=journal)
    return Response(status_code=204)
