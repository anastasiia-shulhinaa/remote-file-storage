// Cancellation of a synchronization = stop + restore the state from before it started.
//
//   1. POST /sync/{id}/cancel     RUNNING → CANCEL_REQUESTED (server accepts no further changes)
//   2. (the executor stops after the change in progress)
//   3. POST /sync/{id}/rollback   → ROLLING_BACK; the server reverses the remote changes
//   4. LocalJournal.rollback      the browser reverses its local changes
//   5. POST /sync/{id}/rollback/finish → CANCELLED, or ROLLBACK_FAILED with the details
//
// Every step is idempotent, so the same function also resumes an interrupted rollback.

import { syncApi } from "../api/client";
import type { RollbackFailure, SyncCounts, SynchronizationDetails } from "../api/types";
import { ApiError } from "../lib/errors";
import { saveBaseline } from "./baseline";
import type { LocalJournal } from "./localJournal";

export interface RollbackOutcome {
  details: SynchronizationDetails;
  failures: (RollbackFailure & { side: "local" | "remote" })[];
}

/** Step 1 (idempotent). A synchronization that already finished cannot be cancelled. */
export async function requestCancel(synchronizationId: string): Promise<void> {
  try {
    await syncApi.cancel(synchronizationId);
  } catch (error) {
    if (!(error instanceof ApiError && error.code === "sync_cancelled")) throw error;
  }
}

/** Steps 3–5, after the executor has stopped. */
export async function rollbackSynchronization(
  synchronizationId: string,
  root: FileSystemDirectoryHandle | null,
  journal: LocalJournal | null,
  onRestoring: () => void,
  counts?: SyncCounts,
): Promise<RollbackOutcome> {
  onRestoring();
  await syncApi.rollback(synchronizationId);

  let localRestored = 0;
  let localFailures: RollbackFailure[] = [];
  if (journal && root) {
    const local = await journal.rollback(root);
    localRestored = local.restored;
    localFailures = local.failures.map((e) => ({ relative_path: e.path, operation: e.kind, code: e.error ?? "local_io_error" }));
    saveBaseline(journal.data.remoteFolderId, journal.data.folderName, local.baseline);
  } else if (journal) {
    // the journal exists but the folder is not accessible any more
    localFailures = [{ relative_path: journal.data.folderName, operation: "LOCAL_ROLLBACK", code: "local_permission_denied" }];
  }

  const details = await syncApi.finishRollback(synchronizationId, {
    local_restored: localRestored,
    local_failures: localFailures,
    counts,
  });
  if (details.status === "CANCELLED" && journal) await journal.discard();

  const report = details.rollback_report;
  const failures = [
    ...(report?.remote_failures ?? []).map((f) => ({ ...f, side: "remote" as const })),
    ...(report?.local_failures ?? []).map((f) => ({ ...f, side: "local" as const })),
  ];
  return { details, failures };
}
