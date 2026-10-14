# UML → code mapping

## Use cases

| Use case | Endpoint | Code |
|---|---|---|
| Register / Login / Logout | `POST /auth/register`, `/auth/login`, `/auth/logout` | `api/auth.py` → `AuthService` |
| View Virtual Disk | `GET /folders`, `GET /files` | `FolderService.list_folders`, `FileService.list_files` |
| View File Metadata | `GET /files/{id}` | `FileService.get_file` |
| Upload File | `POST /files` | `FileService.upload_file` |
| Download File | `GET /files/{id}/content` | `FileService.download_file` |
| Delete File | `DELETE /files/{id}` | `FileService.delete_file` |
| View File Content | `GET /files/{id}/preview` | `FileService.preview_file` → `PreviewService` |
| Sort / Filter Files | `GET /files?sort=&order=&extension=&recursive=` | `sort_files`, `filter_by_extension` (`.jpg` = all JPEG extensions); `recursive` adds the files of subfolders with `folder_path` |
| Empty Folder | `DELETE /folders/{id}/contents` | `FolderService.clear_folder` |
| Configure Visible Columns | `GET/PATCH /settings/columns` | `ColumnSettingsService`; desktop *Columns* menu, web `ColumnsMenu` |
| Synchronize | `POST /sync`, `PATCH /synchronizations/{id}` | `SynchronizationService` + desktop `SyncDialog` / web `SyncPage` |
| View Synchronization History | `GET /synchronizations` | `SynchronizationService.list_history`; web *Synchronize → History* |

## High-level classes

| Class | Code |
|---|---|
| User | `public.users` + `UserRepository`, `UserDto` |
| VirtualDisk | the user's root folder (`parent_folder_id is null`), `FolderService.ensure_root` |
| Folder | `public.folders`, `FolderDto`, `FolderService` |
| File | `public.files`, `FileDto`, `FileService` |
| Synchronization | `public.synchronizations` (persistent summary), `SynchronizationDto`; the plan (`SynchronizationPlan`) is transient |
| ColumnVisibilitySettings | `public.column_visibility_settings`, `backend/app/schemas/settings.py`, `desktop/app/column_settings.py` |

## VOPC: Synchronization

| Class | File |
|---|---|
| SyncDialog | `desktop/app/sync/sync_page.py`, web `web/src/pages/SyncPage.tsx` |
| LocalFolderScanner | `desktop/app/sync/scanner.py`, web `web/src/sync/scanner.ts` (File System Access API) |
| SyncExecutor | `desktop/app/sync/executor.py`, web `web/src/sync/executor.ts` |
| ApiClient | `desktop/app/api_client.py` (`post_sync`, `report_synchronization`), web `web/src/api/client.ts` (`syncApi`) |
| SynchronizationRepository | `backend/app/repositories/synchronization_repository.py` |
| SynchronizationController | `backend/app/api/sync.py` |
| SynchronizationService | `backend/app/services/synchronization_service.py` |
| FileComparator | `backend/app/synchronization/comparator.py` |
| SyncConflictResolver | `backend/app/synchronization/conflict_resolver.py` |
| FileRepository | `backend/app/repositories/file_repository.py` (via `RemoteFolderScanner`) |
| StorageService | `backend/app/storage/storage_service.py` (used when the plan is executed) |
| SynchronizationPlan | `backend/app/schemas/sync.py` |

## VOPC: Preview

| Class | File |
|---|---|
| FileViewer | `desktop/app/preview.py` (`PreviewDialog`), web `web/src/components/PreviewModal.tsx` + `DocumentViewers.tsx` (pdf.js, sandboxed DOCX) |
| ApiClient | `desktop/app/api_client.py` (`get_preview`), web `fileApi.preview` |
| FileController | `backend/app/api/preview.py` |
| FileService | `backend/app/services/file_service.py` (`preview_file`) |
| PreviewService, TextPreviewer (.c .cpp .py .txt), ImagePreviewer (.png .jpg), PdfPreviewer, DocxPreviewer | `backend/app/services/preview_service.py` |
| FileRepository / StorageService | metadata / content |
| PreviewResponse | `backend/app/schemas/file.py` |

Diagrams in PlantUML: [`diagrams/`](diagrams/). Render them at <https://www.plantuml.com/plantuml> or with the VS Code PlantUML extension.

## Web client (React + TypeScript + Vite)

| Concern | Code |
|---|---|
| Typed REST contract | `web/src/api/types.ts` (mirrors `backend/app/schemas`) |
| REST client, Bearer token, refresh on 401 | `web/src/api/client.ts` — the only module that calls `fetch` |
| Session / auth state | `web/src/auth/AuthContext.tsx`, `web/src/pages/AuthPage.tsx` |
| Disk, folders, files, upload, drag-and-drop, delete confirmation | `web/src/pages/DrivePage.tsx`, `components/FolderTree.tsx`, `components/FileTable.tsx` |
| Filter (all / .c / .jpg), sort, columns | `components/Controls.tsx` (`Segmented`, `SortControl`, `ColumnsMenu`) |
| Browser synchronization | `web/src/sync/` — `fsAccess.ts` (capability detection, picker), `scanner.ts`, `executor.ts`, `paths.ts`, `baseline.ts` |

The browser never decides conflicts: it sends the manifest to `POST /sync` and executes the returned plan.
Browsers cannot set a file's modification time, so after a download `baseline.ts` remembers the
downloaded file's `lastModified` and keeps reporting the remote `modified_at` until the user edits the file
(the desktop client uses `os.utime` for the same purpose).

## Authentication

| Concern | Code |
|---|---|
| Supabase Auth boundary (sign up/in, refresh, existence check) | `backend/app/repositories/auth_gateway.py` |
| Email or username login, reliable "user not found" | `backend/app/services/auth_service.py` (`login`, `_login_error`) |
| Username column, `auth_user_exists()` | `supabase/schema.sql`, `supabase/migrations/002_minidrive.sql` |
| Error codes for clients | `backend/app/core/errors.py`, web `web/src/lib/errors.ts` (`describeError`) |
| Localization (UA default, EN) | `web/src/i18n/` |

## Cancellation and rollback

| Concern | Code |
|---|---|
| Session state machine (8 states) | `backend/app/schemas/sync.py` (`SyncStatus`), diagram `diagrams/state_sync_session.puml` |
| Cancel / rollback / finish, lock per target, lease | `backend/app/services/synchronization_service.py` |
| Write-ahead journal of remote changes + Storage backups | `backend/app/synchronization/journal.py`, table `sync_operations` |
| Exactly-once remote rollback | `backend/app/synchronization/rollback.py` (`RemoteRollback`, compare-and-set claims) |
| Journaled uploads/deletes | `POST /files` / `DELETE /files/{id}` with `synchronization_id` → `FileService`, `FolderService.ensure_path` |
| Local journal + rollback (desktop) | `desktop/app/sync/journal.py`, `desktop/app/sync/session.py` |
| Local journal + rollback (web) | `web/src/sync/localJournal.ts` (OPFS + IndexedDB), `web/src/sync/session.ts` |
| Cancel UI, resume banner | `desktop/app/sync/sync_page.py`, `web/src/pages/SyncPage.tsx` |

## Folder upload

| Client | Code |
|---|---|
| Desktop (drag from Explorer / *Додати папку*) | `desktop/app/folder_upload.py`, `desktop/app/drive_page.py` |
| Web (directory drag-and-drop / `webkitdirectory` picker) | `web/src/lib/upload.ts`, `web/src/pages/DrivePage.tsx` |
| Empty folders | `POST /folders/path` → `FolderService.ensure_folder_path` |
