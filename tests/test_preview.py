import base64
import io
import zipfile
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.file import FileDto
from app.services.preview_service import PreviewService
from conftest import make_upload

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF"
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
DOC_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy OLE2 .doc header


def make_docx(text: str) -> bytes:
    """Minimal valid .docx with one paragraph."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>'))
        z.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>'))
        z.writestr("word/document.xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>'))
    return buffer.getvalue()


DOCX_BYTES = make_docx("Звіт з лабораторної")


def make_file(name: str, extension: str, size: int = 0) -> FileDto:
    now = datetime.now(timezone.utc)
    user = uuid4()
    return FileDto(
        id=uuid4(), folder_id=uuid4(), name=name, extension=extension, size=size,
        storage_path=f"x/{name}", created_at=now, modified_at=now,
        uploaded_by=user, modified_by=user,
    )


# --- text / source code ----------------------------------------------------------------


def test_preview_cpp_is_text():
    preview = PreviewService().create_preview(make_file("main.cpp", ".cpp"), b"int main() {}\n")

    assert preview.type == "text"
    assert preview.content == "int main() {}\n"


def test_preview_cpp_invalid_utf8_is_replaced():
    preview = PreviewService().create_preview(make_file("a.cpp", ".cpp"), b"x\xff")

    assert preview.type == "text"
    assert preview.content == "x�"


@pytest.mark.parametrize("name, extension, language", [
    ("lab.c", ".c", "c"),
    ("main.cpp", ".cpp", "cpp"),
    ("script.py", ".py", "python"),
])
def test_source_code_is_text(name, extension, language):
    preview = PreviewService().create_preview(make_file(name, extension), b"print('hi')\n")

    assert preview.type == "text"
    assert preview.language == language
    assert preview.content == "print('hi')\n"


# --- images -----------------------------------------------------------------------------


def test_preview_png_is_base64_image():
    preview = PreviewService().create_preview(make_file("dot.png", ".png"), PNG_BYTES)

    assert preview.type == "image"
    assert preview.mime_type == "image/png"
    assert base64.b64decode(preview.content_base64) == PNG_BYTES


def test_preview_fake_png_is_unavailable():
    preview = PreviewService().create_preview(make_file("fake.png", ".png"), b"not an image")

    assert (preview.type, preview.reason) == ("unavailable", "invalid_content")


def test_preview_jpg_is_image():
    preview = PreviewService().create_preview(make_file("photo.jpg", ".jpg"), JPEG_BYTES)

    assert preview.type == "image"
    assert preview.mime_type == "image/jpeg"


def test_preview_fake_jpg_is_unavailable():
    preview = PreviewService().create_preview(make_file("photo.jpg", ".jpg"), b"not an image at all")

    assert (preview.type, preview.reason) == ("unavailable", "invalid_content")


def test_preview_jfif_is_a_jpeg_image():
    """Windows saves JPEGs from browsers as .jfif."""
    preview = PreviewService().create_preview(make_file("R.jfif", ".jfif"), b"\xff\xd8\xff\xe0rest")

    assert (preview.type, preview.mime_type) == ("image", "image/jpeg")


def test_preview_uses_the_real_image_format():
    """A GIF/PNG that only has a .jpg name is still shown, with its real MIME type."""
    preview = PreviewService().create_preview(make_file("photo.jpg", ".jpg"), b"GIF89a....")

    assert (preview.type, preview.mime_type) == ("image", "image/gif")


# --- documents ----------------------------------------------------------------------------


def test_preview_pdf():
    preview = PreviewService().create_preview(make_file("a.pdf", ".pdf"), PDF_BYTES)

    assert preview.type == "pdf"
    assert base64.b64decode(preview.content_base64) == PDF_BYTES


def test_preview_docx_is_converted_to_html():
    preview = PreviewService().create_preview(make_file("report.docx", ".docx"), DOCX_BYTES)

    assert preview.type == "html"
    assert "<p>Звіт з лабораторної</p>" in preview.content


def test_preview_broken_docx_is_unavailable():
    preview = PreviewService().create_preview(make_file("bad.docx", ".docx"), b"PK\x03\x04garbage")

    assert (preview.type, preview.reason) == ("unavailable", "invalid_content")


def test_legacy_doc_is_honestly_unavailable():
    assert PreviewService().precheck(make_file("old.doc", ".doc")).reason == "legacy_doc"


# --- unavailable --------------------------------------------------------------------------


def test_unsupported_preview():
    preview = PreviewService().create_preview(make_file("archive.zip", ".zip"), b"PK")

    assert preview.type == "unavailable"
    assert preview.reason == "unsupported_type"
    assert preview.message == "Preview unavailable"


def test_too_large_binary_is_rejected_before_download():
    file = make_file("huge.pdf", ".pdf", size=100 * 1024 * 1024)

    assert PreviewService().precheck(file).reason == "too_large"


def test_unsupported_preview_does_not_download(backend, user_id):
    dto = backend.files.upload_file(user_id, None, make_upload("data.bin", b"\x00\x01"))
    backend.storage.objects.clear()  # a download would now fail

    assert backend.files.preview_file(user_id, dto.id).type == "unavailable"


# --- REST API -----------------------------------------------------------------------------


def test_api_preview(client):
    cpp_id = client.post("/files", files={"file": ("a.cpp", b"// hi", "text/plain")}).json()["id"]
    png_id = client.post("/files", files={"file": ("a.png", PNG_BYTES, "image/png")}).json()["id"]

    assert client.get(f"/files/{cpp_id}/preview").json()["content"] == "// hi"
    assert client.get(f"/files/{png_id}/preview").json()["type"] == "image"


def test_api_preview_new_types(client):
    def upload(name, content):
        return client.post("/files", files={"file": (name, content, "application/octet-stream")}).json()["id"]

    assert client.get(f"/files/{upload('a.py', b'x = 1')}/preview").json()["language"] == "python"
    assert client.get(f"/files/{upload('b.jpg', JPEG_BYTES)}/preview").json()["type"] == "image"
    assert client.get(f"/files/{upload('c.pdf', PDF_BYTES)}/preview").json()["type"] == "pdf"
    assert client.get(f"/files/{upload('d.docx', DOCX_BYTES)}/preview").json()["type"] == "html"
    assert client.get(f"/files/{upload('e.doc', DOC_BYTES)}/preview").json()["reason"] == "legacy_doc"
