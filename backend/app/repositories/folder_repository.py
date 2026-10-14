from uuid import UUID

from app.core.supabase import get_supabase


class FolderRepository:
    """Folder metadata. Does not decide authorization — services do."""

    table = "folders"

    def get(self, folder_id: UUID) -> dict | None:
        rows = (
            get_supabase().table(self.table)
            .select("*")
            .eq("id", str(folder_id))
            .limit(1)
            .execute()
        ).data
        return rows[0] if rows else None

    def list_by_user(self, user_id: UUID) -> list[dict]:
        return (
            get_supabase().table(self.table)
            .select("*")
            .eq("user_id", str(user_id))
            .order("name")
            .execute()
        ).data

    def get_root(self, user_id: UUID) -> dict | None:
        rows = (
            get_supabase().table(self.table)
            .select("*")
            .eq("user_id", str(user_id))
            .is_("parent_folder_id", "null")
            .order("created_at")
            .limit(1)
            .execute()
        ).data
        return rows[0] if rows else None

    def find_child(self, user_id: UUID, parent_folder_id: UUID, name: str) -> dict | None:
        rows = (
            get_supabase().table(self.table)
            .select("*")
            .eq("user_id", str(user_id))
            .eq("parent_folder_id", str(parent_folder_id))
            .eq("name", name)
            .limit(1)
            .execute()
        ).data
        return rows[0] if rows else None

    def create(
        self,
        user_id: UUID,
        name: str,
        parent_folder_id: UUID | None,
        folder_id: UUID | None = None,
    ) -> dict:
        """folder_id may be chosen in advance (synchronization journals it before creating)."""
        data = {
            "user_id": str(user_id),
            "parent_folder_id": str(parent_folder_id) if parent_folder_id else None,
            "name": name,
        }
        if folder_id:
            data["id"] = str(folder_id)
        rows = get_supabase().table(self.table).insert(data).execute().data
        return rows[0]

    def delete(self, folder_id: UUID) -> None:
        # files and subfolders are removed by ON DELETE CASCADE
        get_supabase().table(self.table).delete().eq("id", str(folder_id)).execute()
