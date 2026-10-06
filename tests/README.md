# tests/

pytest suites for the Python parts of the project. Configuration is in the root `pytest.ini`, which puts `backend/` and `desktop/` on the import path.

```bash
# from the repository root, with .venv activated
pytest
```

```text
tests/
  conftest.py   shared setup (Qt runs headless via QT_QPA_PLATFORM=offscreen)
  backend/      API, service, domain and ownership tests
  desktop/      desktop client logic and widgets, tested without a real backend
```

External services (backend HTTP, Supabase Auth, PostgreSQL, Storage) are replaced with fakes or mocks in unit tests, so the suite runs without production credentials.

The web client is verified separately from `web/` with `npm run typecheck` and `npm run build`.
