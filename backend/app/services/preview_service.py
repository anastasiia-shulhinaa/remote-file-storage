"""Preview strategies behind GET /files/{id}/preview.

text  — source code / plain text (.c .h .cpp .hpp .cc .py .txt), UTF-8, first 1 MB
image — .png .jpg .jpeg .jfif .jpe .gif .webp .bmp (base64; the real format is taken
        from the content signature, so a JPEG saved as .jfif or a PNG named .jpg still shows)
pdf   — .pdf (base64; rendered by the client)
html  — .docx converted to HTML on the server (mammoth); clients render it sandboxed
unavailable — anything else, with a machine-readable `reason`

Legacy binary .doc files cannot be converted without an office suite, so they are
reported as unavailable (reason "legacy_doc") instead of pretending to render them.
"""

import base64
import io
import logging

from app.schemas.file import FileDto, PreviewResponse

logger = logging.getLogger("minidrive")

MAX_TEXT_PREVIEW_BYTES = 1024 * 1024
MAX_BINARY_PREVIEW_BYTES = 15 * 1024 * 1024
MAX_HTML_PREVIEW_CHARS = 8 * 1024 * 1024

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
PDF_SIGNATURE = b"%PDF-"
ZIP_SIGNATURE = b"PK\x03\x04"

UNAVAILABLE_MESSAGES = {
    "unsupported_type": "Preview unavailable",
    "invalid_content": "The file content does not match its type",
    "too_large": "The file is too large to preview",
    "legacy_doc": "Preview of legacy .doc files is not supported; save the document as .docx",
}


class TextPreviewer:
    languages = {
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".cc": "cpp",
        ".py": "python",
        ".txt": "text",
    }
    extensions = set(languages)
    max_size = None  # large files are truncated, not rejected

    def preview(self, file: FileDto, content: bytes) -> PreviewResponse:
        truncated = len(content) > MAX_TEXT_PREVIEW_BYTES
        text = content[:MAX_TEXT_PREVIEW_BYTES].decode("utf-8", errors="replace")
        return PreviewResponse(
            type="text",
            file_id=file.id,
            name=file.name,
            mime_type="text/plain",
            language=self.languages.get(file.extension.lower(), "text"),
            content=text,
            truncated=truncated,
        )


def sniff_image(content: bytes) -> str | None:
    """MIME type of an image from its first bytes, or None when it is not a supported image."""
    if content.startswith(JPEG_SIGNATURE):
        return "image/jpeg"
    if content.startswith(PNG_SIGNATURE):
        return "image/png"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content[:2] == b"BM":
        return "image/bmp"
    return None


class ImagePreviewer:
    # JPEG is saved under several extensions (Windows often uses .jfif for images from browsers)
    extensions = {".png", ".jpg", ".jpeg", ".jfif", ".jpe", ".gif", ".webp", ".bmp"}
    max_size = MAX_BINARY_PREVIEW_BYTES

    def preview(self, file: FileDto, content: bytes) -> PreviewResponse:
        mime_type = sniff_image(content)
        if mime_type is None:
            return PreviewService.unavailable(file, "invalid_content")
        return PreviewResponse(
            type="image",
            file_id=file.id,
            name=file.name,
            mime_type=mime_type,
            content_base64=base64.b64encode(content).decode("ascii"),
        )


class PdfPreviewer:
    extensions = {".pdf"}
    max_size = MAX_BINARY_PREVIEW_BYTES

    def preview(self, file: FileDto, content: bytes) -> PreviewResponse:
        if not content.startswith(PDF_SIGNATURE):
            return PreviewService.unavailable(file, "invalid_content")
        return PreviewResponse(
            type="pdf",
            file_id=file.id,
            name=file.name,
            mime_type="application/pdf",
            content_base64=base64.b64encode(content).decode("ascii"),
        )


class DocxPreviewer:
    extensions = {".docx"}
    max_size = MAX_BINARY_PREVIEW_BYTES

    def preview(self, file: FileDto, content: bytes) -> PreviewResponse:
        if not content.startswith(ZIP_SIGNATURE):
            return PreviewService.unavailable(file, "invalid_content")
        try:
            import mammoth

            html = mammoth.convert_to_html(io.BytesIO(content)).value
        except Exception as exc:
            logger.info("DOCX preview of %s failed: %s", file.id, exc)
            return PreviewService.unavailable(file, "invalid_content")
        if len(html) > MAX_HTML_PREVIEW_CHARS:
            return PreviewService.unavailable(file, "too_large")
        return PreviewResponse(
            type="html",
            file_id=file.id,
            name=file.name,
            mime_type="text/html",
            content=html,
        )


class PreviewService:
    """Chooses a preview strategy by extension (Strategy pattern)."""

    def __init__(self, previewers: list | None = None):
        self.previewers = previewers or [TextPreviewer(), ImagePreviewer(), PdfPreviewer(), DocxPreviewer()]

    def find_previewer(self, extension: str):
        extension = (extension or "").lower()
        for previewer in self.previewers:
            if extension in previewer.extensions:
                return previewer
        return None

    def precheck(self, file: FileDto) -> PreviewResponse | None:
        """An "unavailable" response decided from metadata alone (no download), or None."""
        extension = (file.extension or "").lower()
        if extension == ".doc":
            return self.unavailable(file, "legacy_doc")
        previewer = self.find_previewer(extension)
        if previewer is None:
            return self.unavailable(file)
        if previewer.max_size is not None and file.size > previewer.max_size:
            return self.unavailable(file, "too_large")
        return None

    def can_preview(self, file: FileDto) -> bool:
        return self.precheck(file) is None

    def create_preview(self, file: FileDto, content: bytes) -> PreviewResponse:
        previewer = self.find_previewer(file.extension)
        if previewer is None:
            return self.precheck(file) or self.unavailable(file)
        return previewer.preview(file, content)

    @staticmethod
    def unavailable(file: FileDto, reason: str = "unsupported_type") -> PreviewResponse:
        return PreviewResponse(
            type="unavailable",
            file_id=file.id,
            name=file.name,
            reason=reason,
            message=UNAVAILABLE_MESSAGES.get(reason, UNAVAILABLE_MESSAGES["unsupported_type"]),
        )
