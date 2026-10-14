from pydantic import BaseModel, ConfigDict

# Optional metadata columns. "name" is not here: it is always visible and cannot be hidden.
OPTIONAL_COLUMNS = ("size", "created_at", "modified_at", "uploaded_by", "modified_by")


class ColumnVisibilitySettings(BaseModel):
    size: bool = True
    created_at: bool = True
    modified_at: bool = True
    uploaded_by: bool = True
    modified_by: bool = True


class ColumnVisibilityUpdate(BaseModel):
    """Partial update; unknown keys (including "name") are rejected with 422."""

    model_config = ConfigDict(extra="forbid")

    size: bool | None = None
    created_at: bool | None = None
    modified_at: bool | None = None
    uploaded_by: bool | None = None
    modified_by: bool | None = None
