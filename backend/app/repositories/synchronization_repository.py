from uuid import UUID

from app.core.supabase import get_supabase


class SynchronizationRepository:
    """Synchronization summaries in public.synchronizations (the plan itself is not stored)."""

    table = "synchronizations"

    def create(self, data: dict) -> dict:
        return get_supabase().table(self.table).insert(data).execute().data[0]

    def get(self, synchronization_id: UUID) -> dict | None:
        rows = (
            get_supabase().table(self.table)
            .select("*")
            .eq("id", str(synchronization_id))
            .limit(1)
            .execute()
        ).data
        return rows[0] if rows else None

    def update(self, synchronization_id: UUID, data: dict) -> dict:
        return (
            get_supabase().table(self.table)
            .update(data)
            .eq("id", str(synchronization_id))
            .execute()
        ).data[0]

    def update_if_status(self, synchronization_id: UUID, statuses: list[str], data: dict) -> dict | None:
        """Compare-and-set: update only while the row still has one of `statuses`.

        Returns the updated row, or None when another request changed the status first.
        This is what makes state transitions (cancel, rollback start/finish) happen once.
        """
        rows = (
            get_supabase().table(self.table)
            .update(data)
            .eq("id", str(synchronization_id))
            .in_("status", statuses)
            .execute()
        ).data
        return rows[0] if rows else None

    def list_with_status(self, user_id: UUID, statuses: list[str]) -> list[dict]:
        return (
            get_supabase().table(self.table)
            .select("*")
            .eq("user_id", str(user_id))
            .in_("status", statuses)
            .execute()
        ).data

    def list_by_user(self, user_id: UUID, limit: int) -> list[dict]:
        return (
            get_supabase().table(self.table)
            .select("*")
            .eq("user_id", str(user_id))
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        ).data
