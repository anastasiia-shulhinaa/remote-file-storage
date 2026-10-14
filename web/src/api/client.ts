// The only place that talks to the backend. Components call these typed functions
// instead of using fetch directly. The browser never talks to Supabase itself.

import type { AuthPolicy } from "../lib/authRules";
import { ApiError } from "../lib/errors";
import type {
  AvailabilityResult,
  ClearFolderResult,
  ColumnSettings,
  FileQuery,
  Folder,
  Preview,
  RegisterResponse,
  RemoteFile,
  Session,
  SyncRequest,
  Synchronization,
  FinishRollbackRequest,
  SynchronizationDetails,
  SynchronizationPlan,
  SynchronizationReport,
  User,
  Uuid,
} from "./types";

const API_URL = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
const SESSION_KEY = "nastusha.session";

export { ApiError };

// --- session -------------------------------------------------------------------

type SessionListener = (session: Session | null) => void;

let session: Session | null = readStoredSession();
const listeners = new Set<SessionListener>();

function readStoredSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function setSession(next: Session | null): void {
  session = next;
  try {
    if (next) localStorage.setItem(SESSION_KEY, JSON.stringify(next));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable (private mode): the session lives in memory only */
  }
  listeners.forEach((listener) => listener(next));
}

export function getSession(): Session | null {
  return session;
}

export function onSessionChange(listener: SessionListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// --- plumbing ------------------------------------------------------------------

interface RequestOptions {
  json?: unknown;
  form?: FormData;
  query?: Record<string, string | number | undefined>;
  auth?: boolean;
}

/** Builds an ApiError from an error response: the backend's `code` plus technical detail. */
async function toApiError(response: Response): Promise<ApiError> {
  let code = "";
  let detail = response.statusText || `HTTP ${response.status}`;
  let extra: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as { detail?: unknown; code?: unknown };
    extra = { ...(body as Record<string, unknown>) };
    if (typeof body.code === "string") code = body.code;
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) {
      // FastAPI request validation (422) has no code of its own
      code ||= "validation_error";
      detail = body.detail.map((d: { msg?: string }) => d.msg ?? String(d)).join("; ");
    }
  } catch {
    /* not JSON */
  }
  return new ApiError(response.status, code || `http_${response.status}`, detail, extra);
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${API_URL}${path}${qs ? `?${qs}` : ""}`;
}

async function send(method: string, path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  } else if (options.form) {
    body = options.form;
  }
  if (options.auth !== false && session) {
    headers["Authorization"] = `Bearer ${session.access_token}`;
  }
  try {
    return await fetch(buildUrl(path, options.query), { method, headers, body });
  } catch {
    throw new ApiError(0, "network_error", "Server is not reachable");
  }
}

// One refresh at a time even when several requests get 401 together.
let refreshing: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  const refreshToken = session?.refresh_token;
  if (!refreshToken) return Promise.resolve(false);
  refreshing ??= (async () => {
    try {
      const response = await send("POST", "/auth/refresh", { json: { refresh_token: refreshToken }, auth: false });
      if (!response.ok) return false;
      setSession((await response.json()) as Session);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function request(method: string, path: string, options: RequestOptions = {}): Promise<Response> {
  let response = await send(method, path, options);

  // access tokens live about an hour: refresh once and retry
  if (response.status === 401 && options.auth !== false && session) {
    if (await refreshSession()) {
      response = await send(method, path, options);
    } else {
      setSession(null);
      throw new ApiError(401, "session_expired", "Session expired");
    }
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return response;
}

async function requestJson<T>(method: string, path: string, options?: RequestOptions): Promise<T> {
  return (await (await request(method, path, options)).json()) as T;
}

// --- auth ----------------------------------------------------------------------

export const authApi = {
  /** identifier: an email or a username (resolved by the backend). */
  async login(identifier: string, password: string): Promise<Session> {
    const next = await requestJson<Session>("POST", "/auth/login", { json: { identifier, password }, auth: false });
    setSession(next);
    return next;
  },

  /** Registration form: is this email / username still free? */
  availability: (fields: { email?: string; username?: string }) =>
    requestJson<AvailabilityResult>("GET", "/auth/availability", { query: fields, auth: false }),

  /** Registration/login rules published by the backend (password length, username format). */
  config: () => requestJson<AuthPolicy>("GET", "/auth/config", { auth: false }),

  async register(
    email: string,
    username: string,
    password: string,
    passwordConfirm: string,
    displayName: string,
  ): Promise<RegisterResponse> {
    const result = await requestJson<RegisterResponse>("POST", "/auth/register", {
      json: { email, username, password, password_confirm: passwordConfirm, display_name: displayName || null },
      auth: false,
    });
    if (result.session) setSession(result.session);
    return result;
  },

  async logout(): Promise<void> {
    try {
      if (session) await send("POST", "/auth/logout", {});
    } finally {
      setSession(null);
    }
  },

  async me(): Promise<User> {
    const user = await requestJson<User>("GET", "/auth/me");
    if (session) setSession({ ...session, user });
    return user;
  },
};

// --- folders -------------------------------------------------------------------

export const folderApi = {
  list: () => requestJson<Folder[]>("GET", "/folders"),

  create: (name: string, parentFolderId: Uuid | null) =>
    requestJson<Folder>("POST", "/folders", { json: { name, parent_folder_id: parentFolderId } }),

  async remove(folderId: Uuid): Promise<void> {
    await request("DELETE", `/folders/${folderId}`);
  },

  /** Deletes all files and subfolders of a folder; the folder itself stays. */
  clear: (folderId: Uuid) => requestJson<ClearFolderResult>("DELETE", `/folders/${folderId}/contents`),

  /** Creates a nested path such as "Project/src" (existing folders are reused). */
  ensurePath: (path: string, parentFolderId: Uuid) =>
    requestJson<Folder>("POST", "/folders/path", { json: { path, parent_folder_id: parentFolderId } }),
};

// --- files ---------------------------------------------------------------------

export interface UploadOptions {
  folderId: Uuid;
  /** "labs/lab1": subfolders of folderId, created if needed (used by synchronization). */
  relativeDir?: string;
  /** Keeps the local modification time (used by synchronization). */
  modifiedAt?: string;
  /** Part of this synchronization: the server journals the change so it can be rolled back. */
  synchronizationId?: Uuid | null;
}

export const fileApi = {
  list: (query: FileQuery) =>
    requestJson<RemoteFile[]>("GET", "/files", {
      query: {
        folder_id: query.folderId,
        extension: query.extension,
        sort: query.sort,
        order: query.order,
        recursive: query.recursive ? "true" : undefined,
      },
    }),

  upload(file: File, options: UploadOptions): Promise<RemoteFile> {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("folder_id", options.folderId);
    if (options.relativeDir) form.append("relative_dir", options.relativeDir);
    if (options.modifiedAt) form.append("modified_at", options.modifiedAt);
    if (options.synchronizationId) form.append("synchronization_id", options.synchronizationId);
    return requestJson<RemoteFile>("POST", "/files", { form });
  },

  async download(fileId: Uuid): Promise<Blob> {
    return (await request("GET", `/files/${fileId}/content`)).blob();
  },

  async remove(fileId: Uuid, synchronizationId?: Uuid | null): Promise<void> {
    await request("DELETE", `/files/${fileId}`, {
      query: synchronizationId ? { synchronization_id: synchronizationId } : undefined,
    });
  },

  preview: (fileId: Uuid) => requestJson<Preview>("GET", `/files/${fileId}/preview`),
};

// --- settings ------------------------------------------------------------------

export const settingsApi = {
  getColumns: () => requestJson<ColumnSettings>("GET", "/settings/columns"),
  updateColumns: (changes: Partial<ColumnSettings>) =>
    requestJson<ColumnSettings>("PATCH", "/settings/columns", { json: changes }),
};

// --- synchronization -----------------------------------------------------------

export const syncApi = {
  plan: (body: SyncRequest) => requestJson<SynchronizationPlan>("POST", "/sync", { json: body }),

  report: (synchronizationId: Uuid, report: SynchronizationReport) =>
    requestJson<Synchronization>("PATCH", `/synchronizations/${synchronizationId}`, { json: report }),

  history: (limit = 20) => requestJson<Synchronization[]>("GET", "/synchronizations", { query: { limit } }),

  details: (synchronizationId: Uuid) =>
    requestJson<SynchronizationDetails>("GET", `/synchronizations/${synchronizationId}`),

  /** RUNNING → CANCEL_REQUESTED (idempotent); the server accepts no further changes. */
  cancel: (synchronizationId: Uuid) => requestJson<Synchronization>("POST", `/sync/${synchronizationId}/cancel`),

  /** Reverses the remote changes (each at most once); may be called again to resume. */
  rollback: (synchronizationId: Uuid) =>
    requestJson<SynchronizationDetails>("POST", `/sync/${synchronizationId}/rollback`),

  /** Reports the local half of the rollback → CANCELLED or ROLLBACK_FAILED. */
  finishRollback: (synchronizationId: Uuid, body: FinishRollbackRequest) =>
    requestJson<SynchronizationDetails>("POST", `/sync/${synchronizationId}/rollback/finish`, { json: body }),
};
