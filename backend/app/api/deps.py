"""Service providers for FastAPI dependency injection (overridable in tests)."""

from functools import lru_cache

from app.core.schema_check import missing_migrations
from app.services.auth_service import AuthService
from app.services.file_service import FileService
from app.services.folder_service import FolderService
from app.services.settings_service import ColumnSettingsService
from app.services.synchronization_service import SynchronizationService


@lru_cache
def get_folder_service() -> FolderService:
    return FolderService()


@lru_cache
def get_file_service() -> FileService:
    return FileService(folder_service=get_folder_service())


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService(folder_service=get_folder_service())


@lru_cache
def get_sync_service() -> SynchronizationService:
    return SynchronizationService(folder_service=get_folder_service())


@lru_cache
def get_settings_service() -> ColumnSettingsService:
    return ColumnSettingsService()


def get_schema_check():
    """Returns the function that lists missing migrations (replaced in tests: no network)."""
    return missing_migrations
