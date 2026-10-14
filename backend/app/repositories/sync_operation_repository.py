from uuid import UUID

from app.core.supabase import get_supabase


class SyncOperationRepository:
    """Journal of remote changes made during a synchronization (public.sync_operations)."""

    table = "sync_operations"

    def create(self, data: dict) -> dict:
        return get_supabase().table(self.table).insert(data).execute().data[0]

    def update(self, operation_id: UUID, data: dict) -> dict | None:
        rows = (
            get_supabase().table(self.table)
            .update(data)
            .eq("id", str(operation_id))
            .execute()
        ).data
        return rows[0] if rows else None

    def update_if_status(
        self,
        operation_id: UUID,
        statuses: list[str],
        data: dict,
        updated_before: str | None = None,
    ) -> dict | None:
        """Compare-and-set claim of one journal entry (each entry is reversed at most once)."""
        query = (
            get_supabase().table(self.table)
            .update(data)
            .eq("id", str(operation_id))
            .in_("status", statuses)
        )
        if updated_before:
            query = query.lt("updated_at", updated_before)
        rows = query.execute().data
        return rows[0] if rows else None

    def list_by_synchronization(self, synchronization_id: UUID) -> list[dict]:
        return (
            get_supabase().table(self.table)
            .select("*")
            .eq("synchronization_id", str(synchronization_id))
            .order("seq")
            .execute()
        ).data
