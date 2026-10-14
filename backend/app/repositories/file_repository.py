from uuid import UUID

from app.core.supabase import get_supabase


class FileRepository:
    """File metadata in PostgreSQL. Does not decide authorization — services do."""

    table = "files"

    def get_by_id(self, file_id: UUID) -> dict | None:
        rows = (
            get_supabase().table(self.table)
            .select("*")
            .eq("id", str(file_id))
            .limit(1)
            .execute()
        ).data
        return rows[0] if rows else None

    def list_by_folder(self, folder_id: UUID) -> list[dict]:
        return (
            get_supabase().table(self.table)
            .select("*")
            .eq("folder_id", str(folder_id))
            .execute()
        ).data

    def list_by_folders(self, folder_ids: list[UUID]) -> list[dict]:
        if not folder_ids:
            return []
        return (
            get_supabase().table(self.table)
            .select("*")
            .in_("folder_id", [str(f) for f in folder_ids])
            .execute()
        ).data

    def find_by_name(self, folder_id: UUID, name: str) -> dict | None:
        rows = (
            get_supabase().table(self.table)
            .select("*")
            .eq("folder_id", str(folder_id))
            .eq("name", name)
            .limit(1)
            .execute()
        ).data
        return rows[0] if rows else None

    def create(self, data: dict) -> dict:
        return get_supabase().table(self.table).insert(data).execute().data[0]

    def update(self, file_id: UUID, data: dict) -> dict:
        return (
            get_supabase().table(self.table)
            .update(data)
            .eq("id", str(file_id))
            .execute()
        ).data[0]

    def delete_many(self, file_ids: list) -> None:
        ids = [str(f) for f in file_ids]
        for start in range(0, len(ids), 200):  # keep the URL of one request short
            get_supabase().table(self.table).delete().in_("id", ids[start:start + 200]).execute()

    def delete(self, file_id: UUID) -> None:
        get_supabase().table(self.table).delete().eq("id", str(file_id)).execute()
