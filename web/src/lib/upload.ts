// Upload of files and whole folders (drag-and-drop or folder picker) into a remote folder.
// The relative structure is preserved: "Project/src/main.py" is uploaded into the remote
// folders Project → src (created by the backend). Nothing is skipped silently: every file
// that cannot be uploaded is reported with its reason.

import { fileApi, folderApi } from "../api/client";
import type { Uuid } from "../api/types";
import { CodedError } from "./errors";

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

export interface UploadItem {
  file: File;
  /** "Project/src/main.py" for a folder upload, "main.py" for a single file. */
  path: string;
}

export interface UploadSelection {
  items: UploadItem[];
  /** Every directory of the selection (relative), including empty ones. */
  dirs: string[];
  /** Top-level names (for the progress title). */
  roots: string[];
}

export interface UploadProgress {
  total: number;
  done: number;
  current: string | null;
}

export interface UploadOutcome {
  uploaded: number;
  replaced: number;
  foldersCreated: number;
  failures: { path: string; error: unknown }[];
}

function dirname(path: string): string {
  const index = path.lastIndexOf("/");
  return index < 0 ? "" : path.slice(0, index);
}

// --- collecting ----------------------------------------------------------------------

function readAllEntries(dir: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
  const reader = dir.createReader();
  const all: FileSystemEntry[] = [];
  return new Promise((resolve, reject) => {
    const next = () =>
      reader.readEntries((batch) => {
        if (batch.length === 0) resolve(all);
        else {
          all.push(...batch);
          next(); // readEntries returns at most ~100 entries per call
        }
      }, reject);
    next();
  });
}

function entryFile(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

async function walk(entry: FileSystemEntry, prefix: string, selection: UploadSelection): Promise<void> {
  const path = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (entry.isDirectory) {
    selection.dirs.push(path);
    for (const child of await readAllEntries(entry as FileSystemDirectoryEntry)) {
      await walk(child, path, selection);
    }
  } else if (entry.isFile) {
    selection.items.push({ file: await entryFile(entry as FileSystemFileEntry), path });
  }
}

/**
 * Files and folders dropped onto the page. Returns null when the browser cannot
 * give access to dropped directories (then the folder picker is the fallback).
 * Call it synchronously from the drop handler: DataTransfer items expire afterwards.
 */
export function collectDropped(dataTransfer: DataTransfer): Promise<UploadSelection> | null {
  const items = Array.from(dataTransfer.items).filter((item) => item.kind === "file");
  if (items.length > 0 && typeof items[0]?.webkitGetAsEntry !== "function") return null;
  const entries = items.map((item) => item.webkitGetAsEntry()).filter((e): e is FileSystemEntry => e !== null);

  return (async () => {
    const selection: UploadSelection = { items: [], dirs: [], roots: entries.map((e) => e.name) };
    for (const entry of entries) await walk(entry, "", selection);
    return selection;
  })();
}

/** <input type="file" webkitdirectory>: files carry their path in webkitRelativePath. */
export function collectFromFolderInput(files: FileList): UploadSelection {
  const selection: UploadSelection = { items: [], dirs: [], roots: [] };
  const dirs = new Set<string>();
  for (const file of Array.from(files)) {
    const path = file.webkitRelativePath || file.name;
    selection.items.push({ file, path });
    for (let dir = dirname(path); dir; dir = dirname(dir)) dirs.add(dir);
  }
  selection.dirs = [...dirs].sort();
  selection.roots = [...new Set(selection.items.map((i) => i.path.split("/")[0] ?? ""))];
  return selection;
}

export function collectFiles(files: File[]): UploadSelection {
  return { items: files.map((file) => ({ file, path: file.name })), dirs: [], roots: files.map((f) => f.name) };
}

// --- uploading -------------------------------------------------------------------------

export async function uploadSelection(
  selection: UploadSelection,
  folderId: Uuid,
  existingNames: Set<string>,
  onProgress: (progress: UploadProgress) => void,
): Promise<UploadOutcome> {
  const outcome: UploadOutcome = { uploaded: 0, replaced: 0, foldersCreated: 0, failures: [] };
  const total = selection.items.length;

  // folders that contain no files are created explicitly (uploads create the others)
  const emptyDirs = selection.dirs.filter(
    (dir) => !selection.items.some((item) => item.path.startsWith(`${dir}/`)) &&
      !selection.dirs.some((other) => other.startsWith(`${dir}/`)),
  );
  for (const dir of emptyDirs) {
    try {
      await folderApi.ensurePath(dir, folderId);
      outcome.foldersCreated++;
    } catch (error) {
      outcome.failures.push({ path: `${dir}/`, error });
    }
  }

  for (const [index, item] of selection.items.entries()) {
    onProgress({ total, done: index, current: item.path });
    if (item.file.size > MAX_UPLOAD_BYTES) {
      outcome.failures.push({ path: item.path, error: new CodedError("file_too_large", "File larger than 50 MB") });
      continue;
    }
    try {
      const relativeDir = dirname(item.path);
      await fileApi.upload(item.file, { folderId, relativeDir: relativeDir || undefined });
      outcome.uploaded++;
      if (!relativeDir && existingNames.has(item.file.name)) outcome.replaced++;
    } catch (error) {
      outcome.failures.push({ path: item.path, error });
    }
  }
  onProgress({ total, done: total, current: null });
  return outcome;
}
