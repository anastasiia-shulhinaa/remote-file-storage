# backend/

FastAPI REST backend shared by the desktop and web clients.

## Responsibilities

- Verify Supabase JWTs and resolve the application user
- Enforce ownership checks on every protected resource
- Store folder, file, column-settings and synchronization metadata in PostgreSQL
- Read and write file bytes in Supabase Storage at server-generated paths (`users/{user_id}/files/{file_id}`)
- Generate previews, apply sorting/filtering, and persist column settings
- Compare a client's local manifest with remote metadata and return a synchronization plan

The backend never accesses a user's local filesystem.

## Run

```bash
# from backend/, with the repository .venv activated
uvicorn app.main:app --reload
```

- `GET /health` returns the service status
- `/docs` opens the interactive OpenAPI documentation

Configuration is read from environment variables or `backend/.env` (see `.env.example`).

## Planned layout

The layout follows the component diagram (`source/diagrams/component.drawio.png`). Only `main.py` and `config.py` exist so far; the other modules are created as each task in `docs/TASKS.md` needs them.

```text
backend/
  app/
    main.py          FastAPI app factory, /health
    config.py        environment-driven settings
    api/             routers (auth, folders, files, preview, settings, sync)
    services/        AuthService, FileService, PreviewService, SyncService, ...
    gateways/        AuthGateway (Supabase Auth), StorageGateway (Supabase Storage)
    repositories/    SQLAlchemy/asyncpg data access
    models/          SQLAlchemy ORM models
    schemas/         Pydantic DTOs (API contracts)
    domain/sync/     comparison, latest-wins resolution and plan building (no I/O)
```
