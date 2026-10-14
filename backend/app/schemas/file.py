from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FileDto(BaseModel):
    id: UUID
    folder_id: UUID
    name: str
    extension: str
    size: int
    storage_path: str
    created_at: datetime
    modified_at: datetime
    uploaded_by: UUID
    modified_by: UUID
    uploaded_by_name: str | None = None
    modified_by_name: str | None = None
    # folder relative to the listed folder: "" = directly in it (only in GET /files)
    folder_path: str | None = None


class FolderDto(BaseModel):
    id: UUID
    user_id: UUID
    parent_folder_id: UUID | None = None
    name: str
    created_at: datetime


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # None → create inside the user's root folder (the Virtual Disk)
    parent_folder_id: UUID | None = None


class FolderPathCreate(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    parent_folder_id: UUID | None = None


class ClearFolderResult(BaseModel):
    deleted_files: int
    deleted_folders: int


class FolderDetails(FolderDto):
    subfolders: list[FolderDto] = []
    files: list[FileDto] = []


class PreviewResponse(BaseModel):
    """text → content (+ language); image / pdf → content_base64; html → content (DOCX);
    unavailable → reason (machine-readable) + message."""

    type: Literal["text", "image", "pdf", "html", "unavailable"]
    file_id: UUID
    name: str
    content: str | None = None
    mime_type: str | None = None
    language: str | None = None
    content_base64: str | None = None
    reason: str | None = None
    message: str | None = None
    truncated: bool = False
