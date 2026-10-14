import logging
from uuid import UUID

from app.core.errors import ServiceUnavailableError
from app.repositories.settings_repository import ColumnSettingsRepository
from app.schemas.settings import OPTIONAL_COLUMNS, ColumnVisibilitySettings, ColumnVisibilityUpdate


logger = logging.getLogger("minidrive")


class ColumnSettingsService:
    """ColumnVisibilitySettings of a user. Missing row → all columns visible."""

    def __init__(self, repository: ColumnSettingsRepository | None = None):
        self.repository = repository or ColumnSettingsRepository()

    def get(self, user_id: UUID) -> ColumnVisibilitySettings:
        row = self._call(self.repository.get, user_id) or {}
        return ColumnVisibilitySettings(**{k: row[k] for k in OPTIONAL_COLUMNS if row.get(k) is not None})

    def update(self, user_id: UUID, update: ColumnVisibilityUpdate) -> ColumnVisibilitySettings:
        current = self.get(user_id)
        merged = current.model_copy(update=update.model_dump(exclude_none=True))
        self._call(self.repository.upsert, user_id, merged.model_dump())
        return merged

    @staticmethod
    def _call(operation, *args):
        try:
            return operation(*args)
        except Exception as exc:
            # e.g. column_visibility_settings is missing (supabase/schema.sql not applied)
            logger.error("Column settings unavailable: %s", exc)
            raise ServiceUnavailableError("Column settings are unavailable", code="settings_unavailable") from exc
