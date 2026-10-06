# MiniDrive — Remote File Storage System

A simplified Google Drive-like remote file storage system built as a university project.
One FastAPI backend serves two clients: a PySide6 desktop application and a React + TypeScript web application.

The authoritative project documentation lives in [`docs/`](docs/):

| Document | Role |
|---|---|
| [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) | Source of truth: requirements, architecture, design decisions |
| [`docs/TASKS.md`](docs/TASKS.md) | Implementation task list (TASK-001 … TASK-081) |
| [`docs/PROJECT_PLAN_DESKTOP.md`](docs/PROJECT_PLAN_DESKTOP.md) | Desktop-stage plan |
| [`docs/PROJECT_PLAN_WEB.md`](docs/PROJECT_PLAN_WEB.md) | Web-stage plan |

UML diagrams and the stage 1.1 report are in [`source/diagrams/`](source/diagrams/).

## Technology stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Pydantic, SQLAlchemy, asyncpg, REST |
| Auth / data / storage | Supabase Auth, Supabase PostgreSQL, Supabase Storage |
| Desktop client | Python, PySide6 |
| Web client | React, TypeScript, Vite, CSS, File System Access API |
| Testing | pytest; TypeScript type checking and production build for the Web client |
| Deployment | Docker, Render |

## Repository structure

```text
backend/   FastAPI application: API routers, services, gateways, repositories, models
desktop/   PySide6 desktop client: GUI, REST API client, local folder scanning and sync execution
web/       React + TypeScript + Vite web client: GUI, REST API client, browser sync
tests/     pytest suites for the backend and desktop client
docs/      Requirements, architecture and implementation plans
source/    UML diagrams and university report artifacts
```

Responsibility boundaries (from `docs/PROJECT_CONTEXT.md`):

- The **backend** is the only component that talks to PostgreSQL and Supabase Storage, and it never touches a user's local filesystem.
- The **clients** do all local filesystem work: they scan local folders, send a manifest to `POST /sync`, and carry out the plan the backend returns.
- The **web client** communicates only with FastAPI over REST. It never receives the service-role key or any database credential.

## Development setup

Prerequisites (tested versions):

- Python 3.13
- Node.js 22.12+ / npm 10 (required by Vite 8)
- Docker 28 (deployment stage only)

### 1. Python environment (backend + desktop + tests)

From the repository root:

```bash
python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# Windows (Git Bash):    source .venv/Scripts/activate
# macOS/Linux:           source .venv/bin/activate
pip install -r requirements-dev.txt
```

| File | Contents |
|---|---|
| `backend/requirements.txt` | Backend runtime: FastAPI, Uvicorn, Pydantic, pydantic-settings, SQLAlchemy (async), asyncpg |
| `desktop/requirements.txt` | Desktop runtime: PySide6, httpx, python-dotenv |
| `requirements-dev.txt` | Both of the above plus pytest and httpx2 (the HTTP client for FastAPI's TestClient) |

### 2. Web dependencies

```bash
cd web
npm install
```

### 3. Configuration

Each component has its own `.env.example`. Copy it and adjust the values:

| Template | Copy to | Contains |
|---|---|---|
| `backend/.env.example` | `backend/.env` | **Server-only** secrets: database URL, Supabase keys, CORS origins |
| `desktop/.env.example` | `desktop/.env` | Client-safe: backend API URL |
| `web/.env.example` | `web/.env.local` | Client-safe: backend API URL (`VITE_*` values are public) |

All variables have development defaults, so the shells also run without a `.env` file. Real `.env` files are ignored by git.

### 4. Run

| Component | Command (from the given directory) | Result |
|---|---|---|
| Backend | `backend/`: `uvicorn app.main:app --reload` | API at http://127.0.0.1:8000, health check at `/health`, docs at `/docs` |
| Desktop | `desktop/`: `python -m minidrive_desktop` | PySide6 window that checks the backend connection |
| Web | `web/`: `npm run dev` | http://localhost:5173, which checks the backend connection |

### 5. Verify

```bash
# repository root
pytest

# web/
npm run typecheck
npm run build
```

## Implementation status

Implementation follows `docs/TASKS.md` in dependency order. Completed so far:

- [x] TASK-001 — Repository structure
- [x] TASK-002 — Dependencies and environments
- [x] TASK-003 — Environment variables
- [x] TASK-004 — Runnable application shells
