# desktop/

PySide6 desktop client. It communicates with the FastAPI backend over HTTPS/REST.

## Responsibilities

- Provide the GUI: login, folder browser, file metadata table, upload/download/delete, preview, sort/filter, and column settings
- Run the REST API client and handle the session/token
- Access the local filesystem: pick a folder, scan it recursively, and build the local manifest
- Carry out the synchronization plan returned by `POST /sync` (`UPLOAD_LOCAL`, `DOWNLOAD_REMOTE`, `DELETE_LOCAL`, `DELETE_REMOTE`, `UNCHANGED`)
- Display synchronization results

The client never receives Supabase service-role or database credentials. It does not duplicate the backend's conflict-resolution rules.

## Run

```bash
# from desktop/, with the repository .venv activated
python -m minidrive_desktop
```

The backend URL comes from `MINIDRIVE_API_URL` (environment variable or `desktop/.env`, see `.env.example`). It defaults to `http://127.0.0.1:8000`.

## Layout

```text
minidrive_desktop/
  __main__.py        entry point (python -m minidrive_desktop)
  app.py             QApplication bootstrap
  config.py          client-safe configuration
  api/client.py      ApiClient: the only place that talks HTTP to the backend
  ui/main_window.py  PySide6 main window
```
