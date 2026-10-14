from dataclasses import asdict, dataclass

COLUMN_LABELS = {
    "size": "Size",
    "created_at": "Created",
    "modified_at": "Modified",
    "uploaded_by": "Uploaded by",
    "modified_by": "Modified by",
}


@dataclass
class ColumnVisibilitySettings:
    """Which optional columns the file table shows. "Name" is always visible."""

    size: bool = True
    created_at: bool = True
    modified_at: bool = True
    uploaded_by: bool = True
    modified_by: bool = True

    def is_visible(self, column: str) -> bool:
        if column == "name":
            return True
        return getattr(self, column, True)

    def toggle_column(self, column: str) -> bool:
        if column not in COLUMN_LABELS:
            raise ValueError(f"Column {column!r} cannot be hidden")
        setattr(self, column, not getattr(self, column))
        return getattr(self, column)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ColumnVisibilitySettings":
        data = data or {}
        return cls(**{k: bool(data[k]) for k in COLUMN_LABELS if k in data})
