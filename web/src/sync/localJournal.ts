// Write-ahead journal of LOCAL changes made by a browser synchronization.
//
// The server can only reverse remote changes; the browser reverses what it did to the
// chosen folder. Before a local file is overwritten or deleted, its bytes are copied
// into the origin private file system (OPFS) and the journal is saved there too.
// The folder handle is kept in IndexedDB, so a rollback can be resumed after a page
// reload (the browser asks for the folder permission again).

import { CodedError } from "../lib/errors";
import type { Baseline } from "./baseline";
import { splitParent } from "./paths";

export type LocalOperationKind =
  | "CREATE_LOCAL_FILE"
  | "OVERWRITE_LOCAL_FILE"
  | "DELETE_LOCAL_FILE"
  | "CREATE_LOCAL_FOLDER";

export type LocalOperationStatus = "PENDING" | "APPLIED" | "ROLLED_BACK" | "ROLLBACK_FAILED";

export interface LocalJournalEntry {
  seq: number;
  kind: LocalOperationKind;
  path: string;
  /** Name of the backup file in OPFS (overwrite / delete). */
  backup?: string;
  /** The modified_at this file had in the manifest before the sync. */
  reported?: string;
  status: LocalOperationStatus;
  error?: string;
}

export interface LocalJournalData {
  synchronizationId: string;
  remoteFolderId: string;
  folderName: string;
  /** The timestamp baseline before the sync (restored by the rollback). */
  baselineBefore: Baseline;
  entries: LocalJournalEntry[];
  createdAt: string;
}

const ROOT_DIR = "minidrive-journal";
const DB_NAME = "minidrive";
const STORE = "sync-handles";

// --- IndexedDB: directory handles ----------------------------------------------------

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function idb<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = action(db.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result as T);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

export const handleStore = {
  save: (id: string, handle: FileSystemDirectoryHandle) => idb<unknown>("readwrite", (s) => s.put(handle, id)),
  load: (id: string) => idb<FileSystemDirectoryHandle | undefined>("readonly", (s) => s.get(id)),
  remove: (id: string) => idb<unknown>("readwrite", (s) => s.delete(id)),
};

// --- OPFS -----------------------------------------------------------------------------

async function journalsRoot(): Promise<FileSystemDirectoryHandle> {
  const root = await navigator.storage.getDirectory();
  return root.getDirectoryHandle(ROOT_DIR, { create: true });
}

async function writeFile(dir: FileSystemDirectoryHandle, name: string, data: Blob | string): Promise<void> {
  const handle = await dir.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  await writable.write(data);
  await writable.close();
}

export async function getDirectory(
  root: FileSystemDirectoryHandle,
  dirs: string[],
  create: boolean,
): Promise<FileSystemDirectoryHandle> {
  let dir = root;
  for (const name of dirs) dir = await dir.getDirectoryHandle(name, { create });
  return dir;
}

async function exists(root: FileSystemDirectoryHandle, path: string, kind: "file" | "directory"): Promise<boolean> {
  const { dirs, name } = splitParent(path);
  try {
    const dir = await getDirectory(root, dirs, false);
    if (kind === "file") await dir.getFileHandle(name);
    else await dir.getDirectoryHandle(name);
    return true;
  } catch (error) {
    if (error instanceof DOMException && (error.name === "NotFoundError" || error.name === "TypeMismatchError")) {
      return false;
    }
    throw error;
  }
}

export class LocalJournal {
  private constructor(
    readonly data: LocalJournalData,
    private readonly dir: FileSystemDirectoryHandle,
  ) {}

  static async create(
    synchronizationId: string,
    remoteFolderId: string,
    root: FileSystemDirectoryHandle,
    baselineBefore: Baseline,
  ): Promise<LocalJournal> {
    const dir = await (await journalsRoot()).getDirectoryHandle(synchronizationId, { create: true });
    const journal = new LocalJournal(
      {
        synchronizationId,
        remoteFolderId,
        folderName: root.name,
        baselineBefore: structuredClone(baselineBefore),
        entries: [],
        createdAt: new Date().toISOString(),
      },
      dir,
    );
    await journal.save();
    await handleStore.save(synchronizationId, root);
    return journal;
  }

  /** Journals left by an interrupted synchronization (page reloaded / closed). */
  static async listStored(): Promise<LocalJournal[]> {
    const result: LocalJournal[] = [];
    const root = await journalsRoot();
    for await (const [name, handle] of (root as unknown as { entries(): AsyncIterable<[string, FileSystemHandle]> }).entries()) {
      if (handle.kind !== "directory") continue;
      try {
        const dir = handle as FileSystemDirectoryHandle;
        const file = await (await dir.getFileHandle("journal.json")).getFile();
        result.push(new LocalJournal(JSON.parse(await file.text()) as LocalJournalData, dir));
      } catch {
        await root.removeEntry(name, { recursive: true }).catch(() => undefined);
      }
    }
    return result;
  }

  private async save(): Promise<void> {
    await writeFile(this.dir, "journal.json", JSON.stringify(this.data));
  }

  /** Removes the journal and its backups (after success or a successful rollback). */
  async discard(): Promise<void> {
    await (await journalsRoot()).removeEntry(this.data.synchronizationId, { recursive: true }).catch(() => undefined);
    await handleStore.remove(this.data.synchronizationId).catch(() => undefined);
  }

  // --- write-ahead entries ---------------------------------------------------------------

  private async add(entry: Omit<LocalJournalEntry, "seq" | "status">, backupOf?: File): Promise<LocalJournalEntry> {
    const full: LocalJournalEntry = { ...entry, seq: this.data.entries.length + 1, status: "PENDING" };
    if (backupOf) {
      full.backup = `backup-${full.seq}`;
      await writeFile(this.dir, full.backup, backupOf); // the backup is saved before the change
    }
    this.data.entries.push(full);
    await this.save();
    return full;
  }

  async applied(entry: LocalJournalEntry): Promise<void> {
    entry.status = "APPLIED";
    await this.save();
  }

  /** Before writing a downloaded file: back up the existing one, or remember that it is new. */
  async beforeWrite(root: FileSystemDirectoryHandle, path: string, reported?: string): Promise<LocalJournalEntry> {
    const { dirs, name } = splitParent(path);
    // folders that do not exist yet are created by the sync → journaled, removed on rollback
    for (let depth = 1; depth <= dirs.length; depth++) {
      const dirPath = dirs.slice(0, depth).join("/");
      if (!(await exists(root, dirPath, "directory"))) {
        const created = await this.add({ kind: "CREATE_LOCAL_FOLDER", path: dirPath });
        await getDirectory(root, dirs.slice(0, depth), true);
        await this.applied(created);
      }
    }
    if (await exists(root, path, "file")) {
      const dir = await getDirectory(root, dirs, false);
      const current = await (await dir.getFileHandle(name)).getFile();
      return this.add({ kind: "OVERWRITE_LOCAL_FILE", path, reported }, current);
    }
    return this.add({ kind: "CREATE_LOCAL_FILE", path });
  }

  /** Before deleting a local file: keep its bytes. */
  async beforeDelete(root: FileSystemDirectoryHandle, path: string, reported?: string): Promise<LocalJournalEntry> {
    const { dirs, name } = splitParent(path);
    const dir = await getDirectory(root, dirs, false);
    const current = await (await dir.getFileHandle(name)).getFile();
    return this.add({ kind: "DELETE_LOCAL_FILE", path, reported }, current);
  }

  // --- rollback -------------------------------------------------------------------------

  /**
   * Reverses the local changes, newest first. Entries already rolled back are skipped,
   * so a resumed rollback never repeats a step. Returns the restored baseline.
   */
  async rollback(root: FileSystemDirectoryHandle): Promise<{ restored: number; failures: LocalJournalEntry[]; baseline: Baseline }> {
    const baseline: Baseline = structuredClone(this.data.baselineBefore);
    let restored = 0;
    for (const entry of [...this.data.entries].reverse()) {
      if (entry.status === "ROLLED_BACK") continue;
      try {
        const lastModified = await this.undo(root, entry);
        if (lastModified !== null && entry.reported) {
          // browsers cannot set mtime: keep reporting the pre-sync timestamp for this content
          baseline[entry.path] = { local: lastModified, remote: entry.reported };
        }
        entry.status = "ROLLED_BACK";
        entry.error = undefined;
        restored++;
      } catch (error) {
        entry.status = "ROLLBACK_FAILED";
        entry.error = error instanceof CodedError ? error.code : error instanceof DOMException ? error.name : "local_io_error";
      }
      await this.save();
    }
    return { restored, failures: this.data.entries.filter((e) => e.status === "ROLLBACK_FAILED"), baseline };
  }

  /** Undo one entry; returns the new lastModified of a restored file (or null). */
  private async undo(root: FileSystemDirectoryHandle, entry: LocalJournalEntry): Promise<number | null> {
    const { dirs, name } = splitParent(entry.path);
    switch (entry.kind) {
      case "CREATE_LOCAL_FILE": {
        try {
          await (await getDirectory(root, dirs, false)).removeEntry(name);
        } catch (error) {
          if (!(error instanceof DOMException && error.name === "NotFoundError")) throw error;
        }
        return null;
      }
      case "CREATE_LOCAL_FOLDER": {
        try {
          // not recursive: a folder that now contains something else is never deleted
          await (await getDirectory(root, dirs, false)).removeEntry(name);
        } catch (error) {
          if (error instanceof DOMException && error.name === "NotFoundError") return null;
          if (error instanceof DOMException && error.name === "InvalidModificationError") {
            throw new CodedError("folder_not_empty", "Folder is not empty");
          }
          throw error;
        }
        return null;
      }
      case "OVERWRITE_LOCAL_FILE":
      case "DELETE_LOCAL_FILE": {
        if (!entry.backup) throw new CodedError("backup_missing", "No backup");
        const backup = await (await this.dir.getFileHandle(entry.backup)).getFile();
        const target = await getDirectory(root, dirs, true);
        const handle = await target.getFileHandle(name, { create: true });
        const writable = await handle.createWritable();
        await writable.write(backup);
        await writable.close();
        return (await handle.getFile()).lastModified;
      }
    }
  }
}
