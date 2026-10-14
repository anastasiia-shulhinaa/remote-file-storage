import logging

from app.core.config import settings
from app.core.errors import StorageError
from app.core.supabase import get_supabase


logger = logging.getLogger("minidrive")


class StorageService:
    """Binary file content in the private Supabase Storage bucket."""

    def _bucket(self):
        return get_supabase().storage.from_(settings.supabase_storage_bucket)

    def upload(self, path: str, content: bytes, content_type: str | None = None) -> None:
        options = {
            "upsert": "true",
            "content-type": content_type or "application/octet-stream",
        }
        try:
            self._bucket().upload(path, content, options)
        except Exception as exc:
            logger.error("Storage upload failed: %s", exc)
            raise StorageError("Storage upload failed") from exc

    def download(self, path: str) -> bytes:
        try:
            return self._bucket().download(path)
        except Exception as exc:
            logger.error("Storage download failed: %s", exc)
            raise StorageError("Storage download failed") from exc

    def copy(self, from_path: str, to_path: str) -> None:
        """Server-side copy inside the bucket (used for synchronization backups)."""
        try:
            self._bucket().copy(from_path, to_path)
        except Exception as exc:
            logger.error("Storage copy failed: %s", exc)
            raise StorageError("Storage copy failed") from exc

    def delete(self, paths: str | list[str]) -> None:
        if isinstance(paths, str):
            paths = [paths]
        if not paths:
            return
        try:
            # Storage accepts up to 1000 keys per request
            for start in range(0, len(paths), 1000):
                self._bucket().remove(paths[start:start + 1000])
        except Exception as exc:
            logger.error("Storage delete failed: %s", exc)
            raise StorageError("Storage delete failed") from exc
