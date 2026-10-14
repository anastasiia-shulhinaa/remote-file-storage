from fastapi import APIRouter, Depends

from app.api.deps import get_settings_service
from app.core.security import CurrentUser, get_current_user
from app.schemas.settings import ColumnVisibilitySettings, ColumnVisibilityUpdate
from app.services.settings_service import ColumnSettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/columns", response_model=ColumnVisibilitySettings)
def get_columns(
    user: CurrentUser = Depends(get_current_user),
    settings: ColumnSettingsService = Depends(get_settings_service),
):
    """Optional metadata columns. Name is always visible and is not part of the settings."""
    return settings.get(user.id)


@router.patch("/columns", response_model=ColumnVisibilitySettings)
def update_columns(
    request: ColumnVisibilityUpdate,
    user: CurrentUser = Depends(get_current_user),
    settings: ColumnSettingsService = Depends(get_settings_service),
):
    return settings.update(user.id, request)
