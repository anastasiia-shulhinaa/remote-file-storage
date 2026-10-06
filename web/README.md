# web/

React + TypeScript + Vite web client. It communicates with the FastAPI backend only over REST.

## Responsibilities

- Provide the browser GUI: authentication, folder browser, file table, upload/download/delete, preview, sort/filter, and column settings
- Keep all API calls in a typed REST client/service layer, not scattered across components
- Synchronize local folders through the File System Access API, in supported Chromium-based browsers, over a secure context
- Show a clear message when the browser does not support local-folder synchronization

The web client must never connect directly to PostgreSQL or Supabase Storage. It must never contain privileged credentials. It consumes the synchronization plan from the backend and does not reimplement the conflict-resolution algorithm.

## Commands

```bash
npm install          # install dependencies
npm run dev          # dev server at http://localhost:5173
npm run typecheck    # strict TypeScript check (tsc -b)
npm run build        # type check + production build into dist/
npm run preview      # serve the production build locally
```

The backend URL comes from `VITE_API_BASE_URL` (`web/.env.local`, see `.env.example`). It defaults to `http://127.0.0.1:8000`. The backend must allow the dev origin through `CORS_ORIGINS`.

## Layout

```text
src/
  main.tsx        React entry point
  App.tsx         application shell
  config.ts       client-safe configuration (VITE_* only)
  api/client.ts   typed REST client: the only place that calls fetch
  api/types.ts    typed API contracts mirroring the backend DTOs
```
