from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_file_service
from app.core.security import CurrentUser, get_current_user
from app.schemas.file import PreviewResponse
from app.services.file_service import FileService

router = APIRouter(prefix="/files", tags=["preview"])


@router.get("/{file_id}/preview", response_model=PreviewResponse)
def preview_file(
    file_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    files: FileService = Depends(get_file_service),
):
    """.cpp → text, .png → base64 image, other → Preview unavailable."""
    return files.preview_file(user.id, file_id)
