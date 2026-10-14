// File System Access API: the browser's way to read and write a folder the user picks.
// Supported in Chromium-based desktop browsers (Chrome, Edge, Opera) over HTTPS or localhost.
// Firefox and Safari do not provide showDirectoryPicker, so web synchronization is unavailable there.

import type { SyncMode } from "../api/types";
import { CodedError } from "../lib/errors";
import { handleStore } from "./localJournal";

interface DirectoryPickerOptions {
  id?: string;
  mode?: "read" | "readwrite";
}

type ShowDirectoryPicker = (options?: DirectoryPickerOptions) => Promise<FileSystemDirectoryHandle>;

export type SyncSupport =
  | { supported: true }
  | { supported: false; reason: "insecure" | "api" };

export function detectSyncSupport(): SyncSupport {
  if (!window.isSecureContext) return { supported: false, reason: "insecure" };
  if (typeof (window as unknown as { showDirectoryPicker?: unknown }).showDirectoryPicker !== "function") {
    return { supported: false, reason: "api" };
  }
  return { supported: true };
}

export class PickerCancelled extends Error {
  constructor() {
    super("Folder selection was cancelled");
    this.name = "PickerCancelled";
  }
}

export type AccessMode = "read" | "readwrite";

/** Asks the user for a local folder. Only read access is requested here: the browser's
 *  "Allow this site to edit files?" question is asked later, and only when the chosen
 *  synchronization mode really writes to this computer (see ensurePermission). */
export async function pickDirectory(): Promise<FileSystemDirectoryHandle> {
  const picker = (window as unknown as { showDirectoryPicker: ShowDirectoryPicker }).showDirectoryPicker;
  try {
    return await picker({ id: "nastusha-sync", mode: "read" });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new PickerCancelled();
    if (error instanceof DOMException && (error.name === "SecurityError" || error.name === "NotAllowedError")) {
      throw new CodedError("local_permission_denied", error.message);
    }
    throw error;
  }
}

/**
 * A folder dragged onto the page. Dropping counts as the user's consent, so the browser
 * grants read access WITHOUT its "Allow this site to view and copy files?" question
 * (which the picker always shows and no website can turn off).
 * Must be called synchronously inside the drop event. Resolves to null when what was
 * dropped is not a folder; returns null when the browser cannot hand out folder handles.
 */
export function droppedDirectory(dataTransfer: DataTransfer): Promise<FileSystemDirectoryHandle | null> | null {
  const item = Array.from(dataTransfer.items).find((i) => i.kind === "file");
  const getHandle = (item as unknown as { getAsFileSystemHandle?: () => Promise<FileSystemHandle | null> } | undefined)
    ?.getAsFileSystemHandle;
  if (!item || typeof getHandle !== "function") return null;
  return getHandle
    .call(item)
    .then((handle) => (handle?.kind === "directory" ? (handle as FileSystemDirectoryHandle) : null));
}

interface PermissionCapable {
  queryPermission?: (d: { mode: AccessMode }) => Promise<PermissionState>;
  requestPermission?: (d: { mode: AccessMode }) => Promise<PermissionState>;
}

/** Checks (and if needed asks for) access before a run: permissions of a remembered folder
 *  end with the browser session unless the user chose "Allow on every visit", and they can
 *  be revoked while the page is open. Must be the first await of a click handler, because
 *  the browser only shows the question right after a user gesture. */
export async function ensurePermission(handle: FileSystemDirectoryHandle, mode: AccessMode): Promise<void> {
  const h = handle as unknown as PermissionCapable;
  if (!h.queryPermission || !h.requestPermission) return;
  if ((await h.queryPermission({ mode })) === "granted") return;
  if ((await h.requestPermission({ mode })) !== "granted") {
    throw new CodedError(
      "local_permission_denied",
      mode === "readwrite" ? "Write access to the local folder was denied" : "Access to the local folder was denied",
    );
  }
}

export function ensureWritePermission(handle: FileSystemDirectoryHandle): Promise<void> {
  return ensurePermission(handle, "readwrite");
}

/** Only these plans write to the computer folder. */
export function needsWriteAccess(mode: SyncMode): boolean {
  return mode !== "mirror_local";
}

// --- the last chosen folder is remembered, so it does not have to be picked every time ----

const LAST_FOLDER_KEY = "last-sync-folder";

export async function rememberFolder(handle: FileSystemDirectoryHandle): Promise<void> {
  await handleStore.save(LAST_FOLDER_KEY, handle).catch(() => undefined);
}

export async function restoreFolder(): Promise<FileSystemDirectoryHandle | null> {
  return (await handleStore.load(LAST_FOLDER_KEY).catch(() => undefined)) ?? null;
}

type DirectoryEntries = AsyncIterable<[string, FileSystemHandle]>;

export function directoryEntries(dir: FileSystemDirectoryHandle): DirectoryEntries {
  return (dir as unknown as { entries(): DirectoryEntries }).entries();
}
