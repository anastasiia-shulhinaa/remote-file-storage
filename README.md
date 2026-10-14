# MiniDrive — a simplified Google Drive

Client-server file storage: a **FastAPI** backend, a **PySide6** desktop client and a
**React + TypeScript + Vite** web client. Metadata lives in **Supabase PostgreSQL**, file content in
**Supabase Storage**, and passwords/JWT in **Supabase Auth**.

```text
Desktop PySide6 ─────┐
                     │ HTTPS / REST
Web React + TS ──────┤
                     ▼
                FastAPI Backend
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
     Supabase Auth PostgreSQL Supabase Storage
```

## Features

| Feature | Where |
|---|---|
| Register / Login (email **or username**) / Logout / Current user | `POST /auth/register`, `/auth/login`, `/auth/logout`, `/auth/refresh`, `GET /auth/me` |
| Form rules (password length, a capital letter and a special sign, email/username format) for both clients; the server checks them again | `GET /auth/config` |
| Registration form: "email / username already taken" while typing | `GET /auth/availability?email=&username=` |
| Virtual Disk, nested folders | `GET/POST /folders`, `GET/DELETE /folders/{id}` |
| Empty a folder (delete all its files and subfolders, keep the folder) | `DELETE /folders/{id}/contents` |
| Upload / list / metadata / download / delete | `POST /files`, `GET /files`, `GET /files/{id}`, `GET /files/{id}/content`, `DELETE /files/{id}` |
| Preview: `.c` `.cpp` `.py` `.txt` → code/text, `.png` `.jpg` `.jpeg` `.jfif` `.gif` `.webp` `.bmp` → image (format detected from the content), `.pdf` → PDF (pdf.js), `.docx` → document (converted to HTML on the server); `.doc` and other types → explained as unavailable | `GET /files/{id}/preview` |
| Filter by extension (`.c` does not match `.cpp`; `.jpg` finds every JPEG: `.jpeg`, `.jfif`, `.jpe`); the filter searches the current folder **and all its subfolders** and shows each file's location | `GET /files?extension=.c&recursive=true` |
| Sort by `created_at` / `modified_at` / `name`, asc/desc | `GET /files?sort=created_at&order=asc` |
| Visible columns, saved per user (Name can't be hidden) | `GET/PATCH /settings/columns`; desktop and web *Columns* menu |
| My Drive shows the subfolders **and** the files of the current folder in one table; *Refresh* (and returning to the window/tab) reloads folders and files changed elsewhere | desktop and web drive page |
| Drag-and-drop upload of files **and whole folders** (structure preserved; "Add folder" button as fallback) | `POST /files` (`relative_dir`), `POST /folders/path` |
| Synchronization of a local folder with a remote one | `POST /sync`; desktop and web *Synchronize* page |
| **Cancel a running synchronization = stop + restore the previous state** (rollback) | `POST /sync/{id}/cancel`, `POST /sync/{id}/rollback`, `POST /sync/{id}/rollback/finish` |
| Synchronization sessions and history (8 states, see below) | `GET /synchronizations`, `GET /synchronizations/{id}`, `PATCH /synchronizations/{id}` |

Synchronization follows the guide: the **client** (desktop, or the web client through the
browser's File System Access API) scans the local folder and executes the plan; the **backend** compares the manifest with remote metadata, resolves conflicts
(the later `modified_at` wins, nobody is asked) and returns the plan. The backend never
touches the user's disk. Modes: *two-way* (default), *mirror local → remote* (produces
`DELETE_REMOTE`) and *mirror remote → local* (produces `DELETE_LOCAL`); both clients ask
for confirmation before running a plan that deletes anything. Every run is a session in
`synchronizations`; the client reports progress and the result there.

### Cancellation and rollback

A running synchronization can be cancelled (*Скасувати синхронізацію*). Cancelling does not just
stop: it **restores the local and the remote state to what it was before the synchronization**.

```text
RUNNING → CANCEL_REQUESTED → ROLLING_BACK → CANCELLED           (everything restored)
                                          → ROLLBACK_FAILED     (details listed; retry possible)
PENDING → RUNNING → COMPLETED | FAILED                          (normal run)
```

- **Remote side (server):** uploads/deletes made with `synchronization_id` are journaled *before*
  they happen (`sync_operations`): the old bytes are copied in Storage to
  `<user_id>/.sync-backups/<sync_id>/…` and the old row is kept as a snapshot. The rollback reverses
  the entries newest first; each entry is claimed with a compare-and-set, so it is reversed exactly
  once even if the rollback is requested twice or resumed after a reconnect.
- **Local side (client):** the backend never touches the local disk, so each client keeps its own
  write-ahead journal and backups — the desktop on disk (`%LOCALAPPDATA%/MiniDrive/sync-journal`,
  modification times restored exactly), the web client in the browser's origin private file
  system + IndexedDB (a reload during a run or rollback shows a *restore* banner).
- After `CANCEL_REQUESTED` the server refuses further changes of that session (`409 sync_cancelled`).
- **Concurrency:** only one active session per folder (including parent/child folders) —
  a second sync or a sync during a rollback gets `409 sync_in_progress`. A PENDING/RUNNING session
  without any activity for 10 minutes is treated as abandoned (closed as `FAILED`, "interrupted").
- Backups are removed after a completed sync or a successful rollback; after `ROLLBACK_FAILED` they
  are kept so the rollback can be retried.

**Web synchronization** needs the File System Access API: Chrome, Edge or Opera on a desktop
computer, over HTTPS or `localhost`. Firefox and Safari show an explanatory message instead (use the
desktop app there). Browsers cannot set a file's modification time, so after a download the web
client remembers the file's `lastModified` (in `localStorage`) and keeps reporting the remote time
until the file is edited, so the next run sees `UNCHANGED` instead of re-uploading it.

## Web client: language, login and errors

- The web client is **Ukrainian by default** with a **UA / EN** switch (top bar and login page);
  the choice is remembered in the browser. Texts live in `web/src/i18n/messages.ts`.
- **Login with email or username.** A username (3–30 characters: `a–z 0–9 _ . -`, case-insensitive)
  is chosen at registration; the backend resolves it to the email and Supabase Auth checks the
  password as usual. Both clients log in with an email or a username (`{"email": …}` is still accepted).
- **Form validation, the same in both clients.** Registration checks: email present and valid,
  username present and valid, password present and at least `PASSWORD_MIN_LENGTH` characters
  (at most 72 bytes, the Supabase limit), password confirmation matches. Login checks that both
  fields are filled. The rules come from `GET /auth/config` (one source of truth:
  `backend/app/core/auth_policy.py`); the backend checks them again and answers `422` with
  `{"code": <first problem>, "problems": [<all codes>], "password_min_length": n}`, so every
  problem is shown at once, in Ukrainian or English. Wrong credentials are always
  "Введено некоректні дані для входу." Stricter Supabase password rules are reported as `weak_password`.
- **"User not found" vs "wrong password".** Supabase answers both with `invalid_credentials`, so the
  backend only reports `user_not_found` when it knows for certain: the username/email has no profile
  and `public.auth_user_exists()` (service-role-only SQL function) confirms there is no account.
  If that check is unavailable, the answer stays "incorrect login details" — it is never guessed.
- Every API error carries a stable `code` (`{"detail": …, "code": "user_not_found"}`); the web client
  translates codes and never shows raw backend or Supabase messages. Unexpected exceptions are logged
  on the server and returned as `internal_error`.

## Repository layout

```text
backend/app/
  main.py                 FastAPI app, error handlers, routers, serves web/dist when built
  core/                   config, Supabase clients, JWT auth dependency, errors, validation
  api/                    controllers: auth, folders, files, preview, sync, settings
  schemas/                Pydantic DTOs (FileDto, SynchronizationPlan, ChangeKind, …)
  services/               AuthService, FolderService, FileService, PreviewService,
                          SynchronizationService, ColumnSettingsService
  repositories/           User/Folder/File/ColumnSettings/Synchronization repositories (metadata only)
  storage/                StorageService (binary content)
  synchronization/        RemoteFolderScanner, FileComparator, SyncConflictResolver,
                          SyncJournal (write-ahead journal), RemoteRollback
desktop/app/
  main.py                 entry point (LoginWindow → MainWindow), stylesheet, language
  theme.py, widgets.py    MiniDrive look (same colors/icons as the web), reusable widgets
  i18n.py                 UA (default) / EN; shared texts generated from the web (i18n_messages.py)
  api_client.py           ApiClient (httpx, token refresh, error codes)
  login_window.py, main_window.py, drive_page.py, preview.py
  folder_upload.py        folder drag-and-drop / "Add folder" upload
  column_settings.py      ColumnVisibilitySettings
  sync/                   LocalFolderScanner, SyncExecutor, LocalJournal, session (cancel/rollback), SyncPage
web/                      React + TypeScript + Vite client
  src/api/                typed REST contract (types.ts) and the only fetch layer (client.ts)
  src/pages/              AuthPage, DrivePage, SyncPage
  src/components/         FolderTree, FileTable, PreviewModal, Controls (filter/sort/columns), Modal, Toasts
  src/sync/               File System Access API: scanner, executor, local journal, session (cancel/rollback)
supabase/schema.sql       tables, indexes, RLS, private bucket (fresh project)
supabase/migrations/      002 (settings, history, username), 003 (cancellation / rollback)
scripts/sync_i18n.py      copies the web texts into the desktop client
tests/                    backend tests (pytest, no Supabase needed)
desktop/tests/            desktop tests
docs/                     UML → code mapping, PlantUML diagrams
```

## 1. Supabase setup

1. Create a project at <https://supabase.com>.
2. **SQL Editor** → paste and run [`supabase/schema.sql`](supabase/schema.sql).
   **Existing project from an earlier version?** Run the migrations instead, in order:
   [`002_minidrive.sql`](supabase/migrations/002_minidrive.sql) (column settings, history, username)
   and [`003_sync_rollback.sql`](supabase/migrations/003_sync_rollback.sql) (cancellation/rollback:
   new states, `sync_operations` journal, one-active-session index, the `device` column shown as
   "Комп'ютер" in the history). Both are safe to run twice.
   **How to tell whether a migration is missing:** `GET /health` answers
   `{"status": "ok", "database": "migration_required", "missing_migrations": ["003_sync_rollback.sql"]}`,
   the server log names the file, and the synchronization page says the server database has not been
   updated (instead of a generic error). With everything applied it answers `"database": "ok"`.
   This creates `users`, `folders`, `files`, `column_visibility_settings`, `synchronizations`, the
   indexes, RLS policies and the private `files` bucket. The script is idempotent: **if your project
   already has the older schema, run it again** to add the two new tables.
3. **Authentication → Providers → Email**: keep Email + Password enabled. For local
   development you can turn off *Confirm email*.
4. **Project Settings → API**: copy the Project URL, the **publishable/anon** key and the
   **secret/service-role** key.

## 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

Fill in `backend/.env` (copy it from `.env.example` if it's missing). **Never commit it.**

```env
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_KEY=YOUR_SERVER_SIDE_SECRET_KEY
SUPABASE_ANON_KEY=YOUR_PUBLISHABLE_KEY
SUPABASE_STORAGE_BUCKET=files
APP_ENV=development
CORS_ORIGINS=
# must equal Supabase → Authentication → Providers → Email → "Minimum password length" (default 6)
PASSWORD_MIN_LENGTH=6
```

Run:

```bash
uvicorn app.main:app --reload
```

- API health: <http://127.0.0.1:8000/health>
- Swagger: <http://127.0.0.1:8000/docs> (use **Authorize** with the `access_token` from `/auth/login`)
- Web client: <http://127.0.0.1:8000/> once it has been built (`npm run build` in `web/`)

## 3. Web client (React + TypeScript + Vite)

Requires Node.js 20.19+ (22 LTS recommended).

```bash
cd web
npm install
npm run dev          # http://localhost:5173 — proxies API calls to http://127.0.0.1:8000
npm run typecheck    # strict TypeScript check
npm run build        # type check + production build into web/dist
```

During development keep the backend running. Vite forwards `/auth`, `/folders`, `/files`, `/sync`,
`/synchronizations`, `/settings` to FastAPI, so the browser sees one origin and no CORS setup is
needed (set `MINIDRIVE_API_URL` to proxy elsewhere). In production FastAPI serves `web/dist` itself.
The web client contains **no Supabase keys**: it talks only to the REST API, with the same Bearer
tokens as the desktop client (kept in `localStorage`, refreshed automatically on 401).

## 4. Desktop client

```bash
cd desktop
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

The desktop client has the same look, wording (Ukrainian by default, UA/EN switch) and features as
the web client: sidebar with the folder tree, folders + files of the current folder, filter/sort/
columns, previews (code, images, PDF via QtPdf, DOCX), drag-and-drop of files and folders, and the
synchronization page with cancellation and rollback. Login works with an email or a username.

The API address is configuration, never shown to the user (`desktop/app/config.py`), in this order:
the `MINIDRIVE_API_URL` environment variable, `desktop/minidrive.ini`

```ini
[api]
url = https://your-service.onrender.com
```

or the local development server `http://127.0.0.1:8000`. It is not saved in the user's settings.

The synchronization history shows, per session, the client (desktop / web) and the computer:
the desktop client sends the computer's network name, the web client only the browser family and
operating system (for example "Edge · Windows"). Nothing else about the machine is sent.

The desktop texts are generated from the web dictionary — after changing
`web/src/i18n/messages.ts` run `python scripts/sync_i18n.py`.

## 5. Tests

```bash
# backend (from the repository root, backend venv active)
pytest

# desktop
cd desktop
pytest

# web
cd web
npm run typecheck && npm run build
```

The backend tests replace Supabase with in-memory fakes (`tests/fakes.py`). They cover
filtering, sorting, validation and path traversal, upload/download/delete, ownership (403),
preview (cpp/png/unsupported), sync rules (local newer, remote newer, equal timestamps, mirror
modes), synchronization history (status lifecycle, ownership, finished runs are immutable),
column settings (persisted per user, Name cannot be hidden), the REST API with `TestClient`
and serving of the built web client. The desktop tests cover the local scanner, plan execution,
history counts, column settings and the API client's token refresh.

Cancellation/rollback is covered on every level: `tests/test_sync_rollback.py` (remote journal,
exactly-once rollback, concurrency, failures) and `desktop/tests/test_sync_cancel_integration.py`,
which runs the desktop client against the real backend in a subprocess and checks the critical
acceptance condition `LOCAL_AFTER == LOCAL_BEFORE` (bytes + modification times) and
`REMOTE_AFTER == REMOTE_BEFORE` (every metadata field + bytes) after cancelling at different points,
during deletions, and after a simulated crash.

## 6. Deployment on Render

The root `Dockerfile` builds the web client (Node stage) and runs FastAPI (Python stage), which
serves the API and the static web client from one HTTPS origin:

```text
Browser ── HTTPS ──> Render (Docker) ── FastAPI ──┬── REST API ──> Supabase Auth / PostgreSQL / Storage
                                                  └── web/dist (React build, static files)
```

Local check: `docker build -t minidrive . && docker run -p 8000:8000 --env-file backend/.env minidrive`.

1. Push the repository to GitHub (`backend/.env` is git-ignored).
2. Render → **New → Blueprint** → select the repository. `render.yaml` creates the
   `minidrive` Docker web service.
3. In the Render Dashboard set `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_ANON_KEY` (and
   `CORS_ORIGINS` only if the web client is hosted on a different origin).
4. After deploy, open `https://<service>.onrender.com/` (web client), `/health` and `/docs`, then
   enter that URL in the desktop login window.

A free Render service sleeps when idle (the first request can take about a minute), and its
disk is ephemeral. That's why every file is stored in Supabase Storage.

## Security

- The service-role key is used only by the backend. It is never sent to the desktop, the browser or Git.
- Passwords are handled only by Supabase Auth; `public.users` stores the profile.
- Every request is authorised by a verified JWT (`auth.get_claims`). The user id always comes
  from the token, never from the request body.
- Ownership is checked in services: `current_user → folder.user_id → file.folder_id`
  (foreign files and folders → **403**). RLS policies back this up for direct access.
- File names are validated. Storage keys are generated (`<user_id>/<folder_id>/<file_id>/<safe name>`),
  so there is no path traversal on the server. Both clients refuse sync paths outside the chosen folder,
  and the web client never sends a local absolute path (only paths relative to the picked folder).
- Uploads are limited to 50 MB. The Storage bucket is private. CORS is closed unless `CORS_ORIGINS` is set.
- The web client is a static bundle without secrets (`VITE_*` variables are public, so only the
  optional API URL lives there). It uses Bearer tokens like the desktop client.

## Demo script

1. Log in (desktop) → the Virtual Disk (*My Drive* / *Мій диск*) opens.
2. Show file metadata (table columns, *View* dialog).
3. Upload a `.cpp` → *View* → text preview.
4. Upload a `.png` → *View* → image preview.
5. Filter `.jpg`, then sort by creation date (↑/↓).
6. Hide and show columns (*Columns* menu).
7. Drag a file from Explorer onto the table (drag-and-drop upload).
8. Delete a file.
9. **Synchronize**: create `lab1.cpp` remotely (older), then edit the same file in the local
   folder (newer: local 15:00, remote 14:00) → the plan shows `UPLOAD_LOCAL`, because the
   newer version wins automatically. Run it again: everything is `UNCHANGED`.
10. Open the web version (`/`): filter with *All files / .c / .jpg*, preview, drag-and-drop.
11. Web **Synchronize** (Chrome/Edge): choose a local folder → *Synchronize now* → the plan and the
    result appear; the *History* table shows both desktop and web runs. Then Swagger at `/docs`.
