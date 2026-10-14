import { fileApi } from "../api/client";
import type { ChangeKind, FileChange, SyncCounts, SynchronizationPlan } from "../api/types";
import { ApiError, CodedError } from "../lib/errors";
import type { Baseline } from "./baseline";
import { getDirectory, type LocalJournal } from "./localJournal";
import { splitParent } from "./paths";
import type { ScannedFile } from "./scanner";

// Executes the plan returned by POST /sync against the folder the user picked.
// The plan decides *what* happens (server-side conflict resolution); this module
// performs it with the browser's filesystem and the file endpoints.
//
// Every change can be reversed: remote changes are journaled by the server
// (synchronization_id), local ones by the LocalJournal before they happen.
// Cancellation is checked before every change; a change already in progress finishes
// (it is journaled, so the rollback reverses it as well).

export type ChangeState = "pending" | "running" | "done" | "failed" | "skipped";

export interface SyncResult {
  counts: SyncCounts;
  /** Raw errors; the UI translates them, the history stores a technical text. */
  errors: { path: string; error: unknown }[];
  /** True when execution stopped because of a cancellation. */
  stopped: boolean;
}

const COUNT_KEY: Record<ChangeKind, keyof SyncCounts> = {
  UPLOAD_LOCAL: "uploaded",
  DOWNLOAD_REMOTE: "downloaded",
  DELETE_LOCAL: "deleted_local",
  DELETE_REMOTE: "deleted_remote",
  UNCHANGED: "unchanged",
};

export function emptyCounts(): SyncCounts {
  return { uploaded: 0, downloaded: 0, deleted_local: 0, deleted_remote: 0, unchanged: 0, failed: 0 };
}

/** Raised inside a change when the cancel request arrived before it modified anything. */
class Stopped extends Error {}

function isCancelledByServer(error: unknown): boolean {
  return error instanceof ApiError && error.code === "sync_cancelled";
}

export interface ExecutorHooks {
  onProgress: (index: number, state: ChangeState, error?: unknown) => void;
  shouldStop: () => boolean;
}

export class BrowserSyncExecutor {
  constructor(
    private readonly root: FileSystemDirectoryHandle,
    private readonly remoteFolderId: string,
    private readonly synchronizationId: string | null,
    private readonly scanned: Map<string, ScannedFile>,
    private readonly baseline: Baseline,
    private readonly journal: LocalJournal | null,
  ) {}

  /** Runs every change; one failed file does not stop the others. A cancel stops before the next one. */
  async execute(plan: SynchronizationPlan, hooks: ExecutorHooks): Promise<SyncResult> {
    const result: SyncResult = { counts: emptyCounts(), errors: [], stopped: false };

    for (const [index, change] of plan.changes.entries()) {
      if (change.kind === "UNCHANGED") {
        result.counts.unchanged++;
        hooks.onProgress(index, "skipped");
        continue;
      }
      if (hooks.shouldStop()) {
        result.stopped = true;
        break;
      }
      hooks.onProgress(index, "running");
      try {
        await this.apply(change, hooks.shouldStop);
        result.counts[COUNT_KEY[change.kind]]++;
        hooks.onProgress(index, "done");
      } catch (error) {
        if (error instanceof Stopped || isCancelledByServer(error)) {
          // nothing was changed by this step; the session is being cancelled
          hooks.onProgress(index, "pending");
          result.stopped = true;
          break;
        }
        result.counts.failed++;
        result.errors.push({ path: change.relative_path, error });
        hooks.onProgress(index, "failed", error);
      }
    }
    return result;
  }

  private async apply(change: FileChange, shouldStop: () => boolean): Promise<void> {
    switch (change.kind) {
      case "UPLOAD_LOCAL":
        return this.uploadLocal(change);
      case "DOWNLOAD_REMOTE":
        return this.downloadRemote(change, shouldStop);
      case "DELETE_REMOTE":
        return this.deleteRemote(change);
      case "DELETE_LOCAL":
        return this.deleteLocal(change);
      case "UNCHANGED":
        return;
    }
  }

  private async uploadLocal(change: FileChange): Promise<void> {
    const { dirs } = splitParent(change.relative_path);
    const scanned = this.scanned.get(change.relative_path);
    if (!scanned) throw new CodedError("local_file_missing", "Local file disappeared after scanning");
    const file = await scanned.handle.getFile();
    await fileApi.upload(file, {
      folderId: this.remoteFolderId,
      relativeDir: dirs.join("/") || undefined,
      // the real local time, so the next run sees both sides as equal
      modifiedAt: new Date(file.lastModified).toISOString(),
      synchronizationId: this.synchronizationId,
    });
    delete this.baseline[change.relative_path];
  }

  private async downloadRemote(change: FileChange, shouldStop: () => boolean): Promise<void> {
    if (!change.remote_file_id) throw new CodedError("missing_remote_id", "Plan entry has no remote file id");
    const { dirs, name } = splitParent(change.relative_path);
    const content = await fileApi.download(change.remote_file_id);
    if (shouldStop()) throw new Stopped(); // downloaded, but nothing written yet

    const reported = this.scanned.get(change.relative_path)?.entry.modified_at;
    const entry = this.journal ? await this.journal.beforeWrite(this.root, change.relative_path, reported) : null;
    const dir = await getDirectory(this.root, dirs, true);
    const handle = await dir.getFileHandle(name, { create: true });
    // createWritable writes to a temporary file and replaces the target on close()
    const writable = await handle.createWritable();
    try {
      await writable.write(content);
      await writable.close();
    } catch (error) {
      await writable.abort().catch(() => undefined);
      throw error;
    }
    if (entry && this.journal) await this.journal.applied(entry);

    if (change.remote_modified_at) {
      const written = await handle.getFile();
      this.baseline[change.relative_path] = { local: written.lastModified, remote: change.remote_modified_at };
    }
  }

  private async deleteRemote(change: FileChange): Promise<void> {
    if (!change.remote_file_id) throw new CodedError("missing_remote_id", "Plan entry has no remote file id");
    await fileApi.remove(change.remote_file_id, this.synchronizationId);
    delete this.baseline[change.relative_path];
  }

  private async deleteLocal(change: FileChange): Promise<void> {
    const { dirs, name } = splitParent(change.relative_path);
    let dir: FileSystemDirectoryHandle;
    try {
      dir = await getDirectory(this.root, dirs, false);
      await dir.getFileHandle(name);
    } catch (error) {
      if (error instanceof DOMException && error.name === "NotFoundError") {
        delete this.baseline[change.relative_path];
        return; // already gone: nothing to delete
      }
      throw error;
    }
    const reported = this.scanned.get(change.relative_path)?.entry.modified_at;
    const entry = this.journal ? await this.journal.beforeDelete(this.root, change.relative_path, reported) : null;
    await dir.removeEntry(name);
    if (entry && this.journal) await this.journal.applied(entry);
    delete this.baseline[change.relative_path];
  }
}
