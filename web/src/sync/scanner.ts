import type { LocalFileEntry } from "../api/types";
import { type Baseline, reportedModifiedAt } from "./baseline";
import { directoryEntries } from "./fsAccess";

// Temporary files Chromium creates while a FileSystemWritableFileStream is open.
const IGNORED = /\.crswap$/i;

export interface ScannedFile {
  entry: LocalFileEntry;
  handle: FileSystemFileHandle;
}

/** Thrown when the user cancels while a (possibly very large) folder is being scanned. */
export class ScanCancelled extends Error {}

/**
 * Builds the local manifest (relative path, size, modification time) by walking the
 * chosen folder recursively. Only metadata is collected: file contents are read later,
 * and only for files the plan says to upload. No absolute path ever leaves the browser.
 */
export async function scanDirectory(
  root: FileSystemDirectoryHandle,
  baseline: Baseline,
  onProgress?: (count: number) => void,
  shouldStop: () => boolean = () => false,
): Promise<Map<string, ScannedFile>> {
  const result = new Map<string, ScannedFile>();

  async function walk(dir: FileSystemDirectoryHandle, prefix: string): Promise<void> {
    for await (const [name, handle] of directoryEntries(dir)) {
      if (shouldStop()) throw new ScanCancelled();
      const path = prefix ? `${prefix}/${name}` : name;
      if (handle.kind === "directory") {
        await walk(handle as FileSystemDirectoryHandle, path);
      } else if (!IGNORED.test(name)) {
        const fileHandle = handle as FileSystemFileHandle;
        const file = await fileHandle.getFile();
        result.set(path, {
          handle: fileHandle,
          entry: {
            relative_path: path,
            size: file.size,
            modified_at: reportedModifiedAt(baseline[path], file.lastModified),
          },
        });
        onProgress?.(result.size);
      }
    }
  }

  await walk(root, "");
  return result;
}
