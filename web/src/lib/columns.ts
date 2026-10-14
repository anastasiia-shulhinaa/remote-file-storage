import { useCallback, useEffect, useRef, useState } from "react";
import { settingsApi } from "../api/client";
import type { ColumnSettings, OptionalColumn } from "../api/types";

// Column visibility lives at the workspace level (not inside the per-folder page),
// so it is loaded once and survives navigation between folders.
// The server (GET/PATCH /settings/columns) is the source of truth; the last known
// settings are cached per user in localStorage so they still apply if the server
// is unreachable, and a failed save is never silently lost.

export const DEFAULT_COLUMNS: ColumnSettings = {
  size: true,
  created_at: true,
  modified_at: true,
  uploaded_by: true,
  modified_by: true,
};

const COLUMN_KEYS = Object.keys(DEFAULT_COLUMNS) as OptionalColumn[];

export type ColumnsStatus = "loading" | "synced" | "local-only";

function cacheKey(userId: string): string {
  return `minidrive.columns.${userId}`;
}

function sanitize(value: unknown): ColumnSettings | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const result = { ...DEFAULT_COLUMNS };
  for (const key of COLUMN_KEYS) {
    if (typeof record[key] === "boolean") result[key] = record[key];
  }
  return result;
}

function readCache(userId: string): ColumnSettings | null {
  try {
    const raw = localStorage.getItem(cacheKey(userId));
    return raw ? sanitize(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

function writeCache(userId: string, columns: ColumnSettings): void {
  try {
    localStorage.setItem(cacheKey(userId), JSON.stringify(columns));
  } catch {
    /* storage unavailable */
  }
}

export interface ColumnSettingsState {
  columns: ColumnSettings;
  status: ColumnsStatus;
  /** Set when the last load or save failed: "load" | "save". */
  problem: "load" | "save" | null;
  toggle: (column: OptionalColumn) => void;
  setAll: (visible: boolean) => void;
}

export function useColumnSettings(userId: string): ColumnSettingsState {
  const [columns, setColumns] = useState<ColumnSettings>(() => readCache(userId) ?? DEFAULT_COLUMNS);
  const [status, setStatus] = useState<ColumnsStatus>("loading");
  const [problem, setProblem] = useState<"load" | "save" | null>(null);
  const latest = useRef(columns);
  const saveSeq = useRef(0);
  // saves run one after another, each with the latest state: quick toggles can never
  // reach the server out of order and leave an older state behind
  const saveQueue = useRef<Promise<void>>(Promise.resolve());

  const apply = useCallback(
    (next: ColumnSettings) => {
      latest.current = next;
      setColumns(next);
      writeCache(userId, next);
    },
    [userId],
  );

  useEffect(() => {
    let cancelled = false;
    settingsApi
      .getColumns()
      .then((server) => {
        if (cancelled) return;
        apply(sanitize(server) ?? DEFAULT_COLUMNS);
        setStatus("synced");
        setProblem(null);
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("local-only");
        setProblem("load");
      });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  const commit = useCallback(
    (next: ColumnSettings) => {
      apply(next); // the table updates immediately
      const seq = ++saveSeq.current;
      saveQueue.current = saveQueue.current.then(async () => {
        if (seq !== saveSeq.current) return; // a newer change will send the newer state
        try {
          await settingsApi.updateColumns(latest.current);
          if (seq !== saveSeq.current) return;
          setStatus("synced");
          setProblem(null);
        } catch {
          if (seq !== saveSeq.current) return;
          setStatus("local-only");
          setProblem("save");
        }
      });
    },
    [apply],
  );

  const toggle = useCallback(
    (column: OptionalColumn) => commit({ ...latest.current, [column]: !latest.current[column] }),
    [commit],
  );

  /** "All" in the columns menu: show or hide every optional column at once (Name always stays). */
  const setAll = useCallback(
    (visible: boolean) =>
      commit(Object.fromEntries(COLUMN_KEYS.map((key) => [key, visible])) as unknown as ColumnSettings),
    [commit],
  );

  return { columns, status, problem, toggle, setAll };
}
