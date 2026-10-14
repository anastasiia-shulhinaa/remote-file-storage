"""In-memory replacements for Supabase-backed repositories and storage."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.core.errors import StorageError


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeUserRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def get(self, user_id):
        return self.rows.get(str(user_id))

    def upsert(self, user_id, email, display_name, username=None):
        if username and any(r.get("username") == username and r["id"] != str(user_id) for r in self.rows.values()):
            raise RuntimeError("duplicate key value violates unique constraint \"uq_users_username\"")
        row = {"id": str(user_id), "email": email, "display_name": display_name,
               "username": username, "created_at": now_iso()}
        self.rows[str(user_id)] = row
        return row

    def get_by_email(self, email):
        return next((r for r in self.rows.values() if r["email"] == email.lower()), None)

    def get_by_username(self, username):
        return next((r for r in self.rows.values() if r.get("username") == username), None)

    def get_display_names(self, user_ids):
        return {uid: self.rows[uid]["display_name"] for uid in user_ids if uid in self.rows}


class FakeFolderRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def get(self, folder_id):
        return self.rows.get(str(folder_id))

    def list_by_user(self, user_id):
        return [r for r in self.rows.values() if r["user_id"] == str(user_id)]

    def get_root(self, user_id):
        roots = [r for r in self.list_by_user(user_id) if r["parent_folder_id"] is None]
        return roots[0] if roots else None

    def find_child(self, user_id, parent_folder_id, name):
        for r in self.list_by_user(user_id):
            if r["parent_folder_id"] == str(parent_folder_id) and r["name"] == name:
                return r
        return None

    def create(self, user_id, name, parent_folder_id, folder_id=None):
        row = {
            "id": str(folder_id or uuid4()),
            "user_id": str(user_id),
            "parent_folder_id": str(parent_folder_id) if parent_folder_id else None,
            "name": name,
            "created_at": now_iso(),
        }
        self.rows[row["id"]] = row
        return row

    def delete(self, folder_id):
        # emulate ON DELETE CASCADE for subfolders
        doomed = {str(folder_id)}
        changed = True
        while changed:
            changed = False
            for r in self.rows.values():
                if r["parent_folder_id"] in doomed and r["id"] not in doomed:
                    doomed.add(r["id"])
                    changed = True
        for fid in doomed:
            self.rows.pop(fid, None)
        self.on_delete(doomed)

    def on_delete(self, folder_ids):
        pass


class FakeFileRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def get_by_id(self, file_id):
        return self.rows.get(str(file_id))

    def list_by_folder(self, folder_id):
        return [r for r in self.rows.values() if r["folder_id"] == str(folder_id)]

    def list_by_folders(self, folder_ids):
        ids = {str(f) for f in folder_ids}
        return [r for r in self.rows.values() if r["folder_id"] in ids]

    def find_by_name(self, folder_id, name):
        for r in self.list_by_folder(folder_id):
            if r["name"] == name:
                return r
        return None

    def create(self, data):
        row = {"created_at": now_iso(), **data}
        self.rows[row["id"]] = row
        return row

    def update(self, file_id, data):
        self.rows[str(file_id)].update(data)
        return self.rows[str(file_id)]

    def delete(self, file_id):
        self.rows.pop(str(file_id), None)

    def delete_many(self, file_ids):
        for file_id in file_ids:
            self.rows.pop(str(file_id), None)


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.fail_delete = False
        self.fail_upload_paths: list[str] = []

    def upload(self, path, content, content_type=None):
        if self.fail_upload_paths and any(path.endswith(p) for p in self.fail_upload_paths):
            raise StorageError("Storage upload failed")
        self.objects[path] = content

    def copy(self, from_path, to_path):
        if from_path not in self.objects:
            raise StorageError("Object not found")
        self.objects[to_path] = self.objects[from_path]

    def download(self, path):
        if path not in self.objects:
            raise StorageError("Object not found")
        return self.objects[path]

    def delete(self, paths):
        if self.fail_delete:
            raise StorageError("Storage delete failed")
        for p in [paths] if isinstance(paths, str) else paths:
            self.objects.pop(p, None)


class FakeAuthGateway:
    """Supabase Auth stand-in: accounts with passwords, optional email confirmation."""

    def __init__(self):
        from app.repositories.auth_gateway import AuthGatewayError

        self.Error = AuthGatewayError
        self.accounts: dict[str, dict] = {}  # email → {id, password, metadata, confirmed}
        self.confirm_email = False
        self.existence_check_available = True

    def _response(self, account, with_session=True):
        user = SimpleNamespace(
            id=account["id"], email=account["email"], user_metadata=account["metadata"], identities=[{}],
        )
        session = SimpleNamespace(
            access_token=f"access-{account['id']}", refresh_token=f"refresh-{account['id']}", expires_in=3600,
        ) if with_session else None
        return SimpleNamespace(user=user, session=session)

    def add_account(self, email, password, user_id=None, metadata=None, confirmed=True):
        account = {"id": str(user_id or uuid4()), "email": email, "password": password,
                   "metadata": metadata or {}, "confirmed": confirmed}
        self.accounts[email] = account
        return account

    def sign_up(self, email, password, metadata):
        if email in self.accounts:
            raise self.Error("user_exists")
        if len(password) < 6:
            raise self.Error("weak_password")
        account = self.add_account(email, password, metadata=metadata, confirmed=not self.confirm_email)
        return self._response(account, with_session=not self.confirm_email)

    def sign_in(self, email, password):
        account = self.accounts.get(email)
        if account is None or account["password"] != password:
            raise self.Error("invalid_credentials")
        if not account["confirmed"]:
            raise self.Error("email_not_confirmed")
        return self._response(account)

    def refresh(self, refresh_token):
        for account in self.accounts.values():
            if refresh_token == f"refresh-{account['id']}":
                return self._response(account)
        raise self.Error("session_expired")

    def sign_out(self, access_token):
        pass

    def user_exists(self, email):
        if not self.existence_check_available:
            return None
        return email in self.accounts


class FakeColumnSettingsRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def get(self, user_id):
        return self.rows.get(str(user_id))

    def upsert(self, user_id, data):
        self.rows[str(user_id)] = {"user_id": str(user_id), **data}
        return self.rows[str(user_id)]


class FakeSynchronizationRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.fail_create = False

    ACTIVE = {"PENDING", "RUNNING", "CANCEL_REQUESTED", "ROLLING_BACK"}

    def create(self, data):
        if self.fail_create:
            raise RuntimeError("relation \"synchronizations\" does not exist")
        # emulate the partial unique index uq_synchronizations_active_target
        if data.get("status") in self.ACTIVE and any(
            r["user_id"] == data["user_id"] and r["remote_folder_id"] == data["remote_folder_id"]
            and r["status"] in self.ACTIVE for r in self.rows.values()
        ):
            raise RuntimeError('duplicate key value violates unique constraint "uq_synchronizations_active_target"')
        row = {
            "id": str(uuid4()),
            "uploaded": 0, "downloaded": 0, "deleted_local": 0, "deleted_remote": 0,
            "unchanged": 0, "failed": 0, "error": None, "finished_at": None,
            "rollback_report": None, "updated_at": now_iso(),
            **data,
        }
        self.rows[row["id"]] = row
        return row

    def update_if_status(self, synchronization_id, statuses, data):
        row = self.rows.get(str(synchronization_id))
        if row is None or row["status"] not in statuses:
            return None
        row.update(data)
        return row

    def list_with_status(self, user_id, statuses):
        return [r for r in self.rows.values() if r["user_id"] == str(user_id) and r["status"] in statuses]

    def get(self, synchronization_id):
        return self.rows.get(str(synchronization_id))

    def update(self, synchronization_id, data):
        self.rows[str(synchronization_id)].update(data)
        return self.rows[str(synchronization_id)]

    def list_by_user(self, user_id, limit):
        rows = [r for r in self.rows.values() if r["user_id"] == str(user_id)]
        return sorted(rows, key=lambda r: r["started_at"], reverse=True)[:limit]


class FakeSyncOperationRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.seq = 0

    def create(self, data):
        self.seq += 1
        row = {"seq": self.seq, "error": None, "created_at": now_iso(), "updated_at": now_iso(), **data}
        self.rows[row["id"]] = row
        return row

    def update(self, operation_id, data):
        row = self.rows.get(str(operation_id))
        if row is not None:
            row.update(data)
        return row

    def update_if_status(self, operation_id, statuses, data, updated_before=None):
        row = self.rows.get(str(operation_id))
        if row is None or row["status"] not in statuses:
            return None
        if updated_before and not row["updated_at"] < updated_before:
            return None
        row.update(data)
        return dict(row)

    def list_by_synchronization(self, synchronization_id):
        rows = [r for r in self.rows.values() if r["synchronization_id"] == str(synchronization_id)]
        return [dict(r) for r in sorted(rows, key=lambda r: r["seq"])]


class FakeBackend:
    """All fakes wired together the same way app/api/deps.py wires real services."""

    def __init__(self):
        from app.services.auth_service import AuthService
        from app.services.file_service import FileService
        from app.services.folder_service import FolderService
        from app.services.settings_service import ColumnSettingsService
        from app.services.synchronization_service import SynchronizationService
        from app.synchronization.scanner import RemoteFolderScanner

        self.users = FakeUserRepository()
        self.folder_repo = FakeFolderRepository()
        self.file_repo = FakeFileRepository()
        self.storage = FakeStorage()
        # emulate files ON DELETE CASCADE when folders are deleted
        self.folder_repo.on_delete = lambda ids: [
            self.file_repo.rows.pop(fid)
            for fid, row in list(self.file_repo.rows.items())
            if row["folder_id"] in ids
        ]

        self.folders = FolderService(self.folder_repo, self.file_repo, self.storage)
        self.files = FileService(self.file_repo, self.folders, self.users, self.storage)
        self.auth_gateway = FakeAuthGateway()
        self.auth = AuthService(self.users, self.folders, self.auth_gateway)
        self.sync_history = FakeSynchronizationRepository()
        self.sync_operations = FakeSyncOperationRepository()
        self.sync = SynchronizationService(
            self.folders,
            RemoteFolderScanner(self.folders, self.file_repo),
            history=self.sync_history,
            operations=self.sync_operations,
        )
        self.column_settings_repo = FakeColumnSettingsRepository()
        self.settings = ColumnSettingsService(self.column_settings_repo)

    def add_user(self, email="anna@example.com", name="Anna") -> UUID:
        user_id = uuid4()
        self.users.upsert(user_id, email, name)
        self.folders.ensure_root(user_id)
        return user_id
