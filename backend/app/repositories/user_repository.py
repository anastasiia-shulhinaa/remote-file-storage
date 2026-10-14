from uuid import UUID

from app.core.supabase import get_supabase


class UserRepository:
    """Profiles in public.users (passwords live only in Supabase Auth)."""

    table = "users"

    def _first(self, column: str, value: str) -> dict | None:
        rows = (
            get_supabase().table(self.table)
            .select("*")
            .eq(column, value)
            .limit(1)
            .execute()
        ).data
        return rows[0] if rows else None

    def get(self, user_id: UUID) -> dict | None:
        return self._first("id", str(user_id))

    def get_by_email(self, email: str) -> dict | None:
        return self._first("email", email.lower())

    def get_by_username(self, username: str) -> dict | None:
        """username is stored in lower case (see validation.normalize_username)."""
        return self._first("username", username)

    def upsert(self, user_id: UUID, email: str, display_name: str, username: str | None = None) -> dict:
        data = {
            "id": str(user_id),
            "email": email,
            "display_name": display_name,
        }
        if username:
            data["username"] = username
        rows = get_supabase().table(self.table).upsert(data).execute().data
        return rows[0]

    def get_display_names(self, user_ids: set[str]) -> dict[str, str]:
        if not user_ids:
            return {}
        rows = (
            get_supabase().table(self.table)
            .select("id, display_name")
            .in_("id", sorted(user_ids))
            .execute()
        ).data
        return {row["id"]: row["display_name"] for row in rows}
