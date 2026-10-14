// Browsers cannot set a file's modification time. After DOWNLOAD_REMOTE the local
// copy therefore gets "now" as lastModified, which would look newer than the remote
// file and cause a pointless re-upload on the next run. (The desktop client avoids
// this with os.utime.)
//
// The baseline remembers, per downloaded file, the lastModified the browser gave it
// and the remote modified_at it was downloaded from. While the local file is untouched
// (same lastModified), the scanner reports the remote timestamp, so the backend sees
// equal timestamps → UNCHANGED. Once the user edits the file, lastModified changes and
// the real local time is reported again. Conflict resolution itself stays on the server.

export interface BaselineEntry {
  /** File.lastModified (ms) right after the download was written. */
  local: number;
  /** Remote modified_at (ISO) the file was downloaded from. */
  remote: string;
}

export type Baseline = Record<string, BaselineEntry>;

const PREFIX = "minidrive.sync.baseline.";

function key(remoteFolderId: string, localFolderName: string): string {
  return `${PREFIX}${remoteFolderId}.${localFolderName}`;
}

export function loadBaseline(remoteFolderId: string, localFolderName: string): Baseline {
  try {
    const raw = localStorage.getItem(key(remoteFolderId, localFolderName));
    return raw ? (JSON.parse(raw) as Baseline) : {};
  } catch {
    return {};
  }
}

export function saveBaseline(remoteFolderId: string, localFolderName: string, baseline: Baseline): void {
  try {
    localStorage.setItem(key(remoteFolderId, localFolderName), JSON.stringify(baseline));
  } catch {
    /* storage full or blocked: worst case the next run re-uploads downloaded files */
  }
}

/** The modified_at to report for a local file. */
export function reportedModifiedAt(entry: BaselineEntry | undefined, lastModified: number): string {
  if (entry && entry.local === lastModified) return entry.remote;
  return new Date(lastModified).toISOString();
}
