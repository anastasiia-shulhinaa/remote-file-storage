"""Folder tree helpers (the root folder is the Virtual Disk, shown as "Мій диск" / "My Drive")."""

from app.i18n import tr


def folder_label(folder: dict) -> str:
    return tr("nav.myDrive") if not folder.get("parent_folder_id") else folder["name"]


def breadcrumbs(folders: list[dict], folder_id: str | None) -> list[dict]:
    by_id = {f["id"]: f for f in folders}
    chain = []
    current = by_id.get(folder_id or "")
    while current is not None and len(chain) < 100:
        chain.insert(0, current)
        current = by_id.get(current.get("parent_folder_id") or "")
    return chain


def folder_paths(folders: list[dict]) -> dict[str, str]:
    """{folder_id: "Мій диск / labs / lab1"} for selects and the history."""
    return {f["id"]: " / ".join(folder_label(c) for c in breadcrumbs(folders, f["id"])) for f in folders}
