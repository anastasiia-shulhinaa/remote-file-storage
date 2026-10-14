// REST contract of the FastAPI backend (mirrors backend/app/schemas/*.py).
// Timestamps are ISO-8601 strings; ids are UUID strings.

export type Uuid = string;
export type IsoDateTime = string;

export interface User {
  id: Uuid;
  email: string;
  display_name: string;
  username: string | null;
  root_folder_id: Uuid | null;
}

export interface Session {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number | null;
  user: User;
}

export interface RegisterResponse {
  user_id: Uuid;
  email: string;
  session: Session | null;
  message: string;
}

export interface Folder {
  id: Uuid;
  user_id: Uuid;
  parent_folder_id: Uuid | null;
  name: string;
  created_at: IsoDateTime;
}

export interface RemoteFile {
  id: Uuid;
  folder_id: Uuid;
  name: string;
  extension: string;
  size: number;
  storage_path: string;
  created_at: IsoDateTime;
  modified_at: IsoDateTime;
  uploaded_by: Uuid;
  modified_by: Uuid;
  uploaded_by_name: string | null;
  modified_by_name: string | null;
  /** Folder relative to the listed one: "" = directly in it, "labs/lab1" = in a subfolder. */
  folder_path?: string | null;
}

export type SortField = "created_at" | "modified_at" | "name";
export type SortOrder = "asc" | "desc";

/** Variant requirement: all files, `.c` or `.jpg`. */
export type ExtensionFilter = "" | ".c" | ".jpg";

export interface FileQuery {
  folderId: Uuid;
  extension: ExtensionFilter;
  sort: SortField;
  order: SortOrder;
  /** Also the files of all subfolders (used while a type filter is on). */
  recursive?: boolean;
}

export interface ClearFolderResult {
  deleted_files: number;
  deleted_folders: number;
}

export type Availability = "available" | "taken" | "invalid" | "unknown";

export interface AvailabilityResult {
  email?: Availability;
  username?: Availability;
}

export type PreviewLanguage = "c" | "cpp" | "python" | "text";
export type UnavailableReason = "unsupported_type" | "invalid_content" | "too_large" | "legacy_doc";

/** GET /files/{id}/preview */
export type Preview =
  | { type: "text"; file_id: Uuid; name: string; content: string; language: PreviewLanguage; truncated: boolean }
  | { type: "image"; file_id: Uuid; name: string; content_base64: string; mime_type: string }
  | { type: "pdf"; file_id: Uuid; name: string; content_base64: string }
  | { type: "html"; file_id: Uuid; name: string; content: string }
  | { type: "unavailable"; file_id: Uuid; name: string; reason: UnavailableReason; message: string };

/** Optional metadata columns; Name is always visible and is not part of the settings. */
export interface ColumnSettings {
  size: boolean;
  created_at: boolean;
  modified_at: boolean;
  uploaded_by: boolean;
  modified_by: boolean;
}

export type OptionalColumn = keyof ColumnSettings;

// --- synchronization ---------------------------------------------------------

export type ChangeKind = "UPLOAD_LOCAL" | "DOWNLOAD_REMOTE" | "DELETE_REMOTE" | "DELETE_LOCAL" | "UNCHANGED";
export type SyncMode = "two_way" | "mirror_local" | "mirror_remote";
export type SyncStatus =
  | "PENDING"
  | "RUNNING"
  | "CANCEL_REQUESTED"
  | "ROLLING_BACK"
  | "CANCELLED"
  | "ROLLBACK_FAILED"
  | "COMPLETED"
  | "FAILED";

/** Statuses that keep the target folder locked (a rollback may still be needed). */
export const ACTIVE_SYNC_STATUSES: readonly SyncStatus[] = ["PENDING", "RUNNING", "CANCEL_REQUESTED", "ROLLING_BACK"];

export interface LocalFileEntry {
  /** Relative to the chosen local folder, "/"-separated. Never an absolute path. */
  relative_path: string;
  size: number;
  modified_at: IsoDateTime;
}

export interface SyncRequest {
  remote_folder_id: Uuid;
  manifest: LocalFileEntry[];
  mode: SyncMode;
  client: "web";
  /** Browser family and OS, e.g. "Edge · Windows" (shown in the history). */
  device?: string;
}

export interface FileChange {
  relative_path: string;
  kind: ChangeKind;
  local_modified_at: IsoDateTime | null;
  remote_modified_at: IsoDateTime | null;
  remote_file_id: Uuid | null;
  local_size: number | null;
  remote_size: number | null;
}

export interface SynchronizationPlan {
  remote_folder_id: Uuid;
  mode: SyncMode;
  changes: FileChange[];
  synchronization_id: Uuid | null;
}

export interface SyncCounts {
  uploaded: number;
  downloaded: number;
  deleted_local: number;
  deleted_remote: number;
  unchanged: number;
  failed: number;
}

export interface SynchronizationReport extends SyncCounts {
  status: "RUNNING" | "COMPLETED" | "FAILED";
  error?: string | null;
}

export interface RollbackFailure {
  relative_path: string | null;
  operation: string;
  code: string;
}

export interface RollbackReport {
  remote_restored: number;
  local_restored: number;
  remote_failures: RollbackFailure[];
  local_failures: RollbackFailure[];
}

export interface Synchronization extends SyncCounts {
  id: Uuid;
  user_id: Uuid;
  remote_folder_id: Uuid | null;
  client: string;
  device: string | null;
  mode: SyncMode;
  status: SyncStatus;
  planned_changes: number;
  error: string | null;
  rollback_report: RollbackReport | null;
  started_at: IsoDateTime;
  updated_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
}

export interface SyncOperation {
  id: Uuid;
  seq: number;
  kind: "CREATE_REMOTE_FILE" | "OVERWRITE_REMOTE_FILE" | "DELETE_REMOTE_FILE" | "CREATE_REMOTE_FOLDER";
  relative_path: string | null;
  status: "PENDING" | "APPLIED" | "ROLLING_BACK" | "ROLLED_BACK" | "ROLLBACK_FAILED" | "COMMITTED";
  error: string | null;
}

export interface SynchronizationDetails extends Synchronization {
  operations: SyncOperation[];
}

export interface FinishRollbackRequest {
  local_restored: number;
  local_failures: RollbackFailure[];
  /** What had been done before the cancel (shown in the history; all of it was rolled back). */
  counts?: SyncCounts;
}
