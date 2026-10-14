from uuid import UUID

from app.core.supabase import get_supabase


class ColumnSettingsRepository:
    """Per-user column visibility in public.column_visibility_settings."""

    table = "column_visibility_settings"

    def get(self, user_id: UUID) -> dict | None:
        rows = (
            get_supabase().table(self.table)
            .select("*")
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        ).data
        return rows[0] if rows else None

    def upsert(self, user_id: UUID, data: dict) -> dict:
        rows = (
            get_supabase().table(self.table)
            .upsert({"user_id": str(user_id), **data})
            .execute()
        ).data
        return rows[0]
