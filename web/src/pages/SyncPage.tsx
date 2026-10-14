import { type DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { syncApi } from "../api/client";
import type {
  ChangeKind,
  FileChange,
  Folder,
  SyncCounts,
  Synchronization,
  SynchronizationPlan,
  SynchronizationReport,
  SyncMode,
  SyncStatus,
} from "../api/types";
import { Icon, type IconName } from "../components/Icon";
import { ConfirmDialog } from "../components/Modal";
import { useToast } from "../components/Toasts";
import { type Translate, useI18n } from "../i18n/I18nProvider";
import type { MessageKey } from "../i18n/messages";
import { ApiError, CodedError, describeError, technicalMessage } from "../lib/errors";
import { folderPaths } from "../lib/folders";
import { useFormat } from "../lib/format";
import { type Baseline, loadBaseline, saveBaseline } from "../sync/baseline";
import { BrowserSyncExecutor, type ChangeState, emptyCounts, type SyncResult } from "../sync/executor";
import {
  detectSyncSupport,
  droppedDirectory,
  ensurePermission,
  ensureWritePermission,
  needsWriteAccess,
  PickerCancelled,
  pickDirectory,
  rememberFolder,
  restoreFolder,
} from "../sync/fsAccess";
import { handleStore, LocalJournal } from "../sync/localJournal";
import { ScanCancelled, type ScannedFile, scanDirectory } from "../sync/scanner";
import { deviceLabel } from "../lib/device";
import { requestCancel, rollbackSynchronization, type RollbackOutcome } from "../sync/session";

const MODES: { value: SyncMode; icon: IconName }[] = [
  { value: "two_way", icon: "sync" },
  { value: "mirror_local", icon: "upload" },
  { value: "mirror_remote", icon: "download" },
];

const KIND_META: Record<ChangeKind, { icon: IconName; tone: string }> = {
  UPLOAD_LOCAL: { icon: "upload", tone: "info" },
  DOWNLOAD_REMOTE: { icon: "download", tone: "success" },
  DELETE_REMOTE: { icon: "trash", tone: "danger" },
  DELETE_LOCAL: { icon: "trash", tone: "danger" },
  UNCHANGED: { icon: "equal", tone: "neutral" },
};

const COUNT_KEY: Record<ChangeKind, keyof SyncCounts> = {
  UPLOAD_LOCAL: "uploaded",
  DOWNLOAD_REMOTE: "downloaded",
  DELETE_LOCAL: "deleted_local",
  DELETE_REMOTE: "deleted_remote",
  UNCHANGED: "unchanged",
};

const STATUS_TONE: Record<SyncStatus, string> = {
  PENDING: "neutral",
  RUNNING: "info",
  CANCEL_REQUESTED: "warning",
  ROLLING_BACK: "warning",
  CANCELLED: "neutral",
  ROLLBACK_FAILED: "danger",
  COMPLETED: "success",
  FAILED: "danger",
};

const UNFINISHED: readonly SyncStatus[] = ["PENDING", "RUNNING", "CANCEL_REQUESTED", "ROLLING_BACK", "ROLLBACK_FAILED"];
const SUMMARY_KEYS = ["uploaded", "downloaded", "deleted_remote", "deleted_local", "unchanged", "failed"] as const;
const HEARTBEAT_MS = 3000;

type Phase =
  | "idle"
  | "scanning"
  | "planning"
  | "confirm"
  | "running"
  | "cancelling"
  | "restoring"
  | "done"
  | "cancelled"
  | "cancelled_early"
  | "rollback_failed";

interface RunContext {
  plan: SynchronizationPlan;
  dir: FileSystemDirectoryHandle;
  scanned: Map<string, ScannedFile>;
  baseline: Baseline;
  journal: LocalJournal | null;
}

interface Recovery {
  journal: LocalJournal;
  status: SyncStatus;
}

interface SyncPageProps {
  folders: Folder[];
  defaultFolderId: string;
  onSynced: () => Promise<void>;
}

function summarize(t: Translate, counts: SyncCounts): string {
  const parts = SUMMARY_KEYS.filter((key) => counts[key] > 0).map((key) =>
    t(`sync.summary.${key}`, { n: counts[key] }),
  );
  return parts.length ? parts.join(" · ") : t("sync.summary.nothing");
}

function historySummary(t: Translate, h: Synchronization): string {
  if (h.status === "CANCELLED") {
    const restored = t("history.rolledBack");
    const done = SUMMARY_KEYS.some((key) => key !== "unchanged" && h[key] > 0);
    return done ? `${summarize(t, h)} · ${restored}` : restored.charAt(0).toUpperCase() + restored.slice(1);
  }
  if (h.status === "ROLLBACK_FAILED") {
    const report = h.rollback_report;
    const count = (report?.remote_failures.length ?? 0) + (report?.local_failures.length ?? 0);
    return `${summarize(t, h)} · ${t("history.notRestored", { count })}`;
  }
  return summarize(t, h);
}

function clientLabel(t: Translate, client: string): string {
  return client === "desktop" || client === "web" || client === "api" ? t(`history.client.${client}`) : client;
}

function opLabel(t: Translate, operation: string): string {
  const known = [
    "CREATE_REMOTE_FILE", "OVERWRITE_REMOTE_FILE", "DELETE_REMOTE_FILE", "CREATE_REMOTE_FOLDER",
    "CREATE_LOCAL_FILE", "OVERWRITE_LOCAL_FILE", "DELETE_LOCAL_FILE", "CREATE_LOCAL_FOLDER", "LOCAL_ROLLBACK",
  ] as const;
  const match = known.find((k) => k === operation);
  return match ? t(`sync.op.${match}`) : operation;
}

export function SyncPage({ folders, defaultFolderId, onSynced }: SyncPageProps) {
  const toast = useToast();
  const { t } = useI18n();
  const format = useFormat();
  const support = useMemo(detectSyncSupport, []);
  const paths = useMemo(() => folderPaths(folders, t("nav.myDrive")), [folders, t]);
  const pathById = useMemo(() => new Map(paths.map((p) => [p.id, p.path])), [paths]);

  const [dir, setDir] = useState<FileSystemDirectoryHandle | null>(null);
  const [remoteFolderId, setRemoteFolderId] = useState(defaultFolderId);
  const [mode, setMode] = useState<SyncMode>("two_way");
  const [phase, setPhase] = useState<Phase>("idle");
  const [scanCount, setScanCount] = useState(0);
  const [plan, setPlan] = useState<SynchronizationPlan | null>(null);
  const [states, setStates] = useState<{ state: ChangeState; error?: unknown }[]>([]);
  const [current, setCurrent] = useState<FileChange | null>(null);
  const [result, setResult] = useState<SyncResult | null>(null);
  const [rollback, setRollback] = useState<RollbackOutcome | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [hideUnchanged, setHideUnchanged] = useState(true);
  const [history, setHistory] = useState<Synchronization[] | null>(null);
  // null = loaded fine; otherwise the message key to show (the actual cause when the server knows it)
  const [historyError, setHistoryError] = useState<MessageKey | null>(null);
  const historyFailed = historyError !== null;
  const [recoveries, setRecoveries] = useState<Recovery[]>([]);
  const run = useRef<RunContext | null>(null);
  const stopRequested = useRef(false);
  const progressCounts = useRef<SyncCounts>(emptyCounts());

  const busy = ["scanning", "planning", "confirm", "running", "cancelling", "restoring"].includes(phase);
  const protectedPhase = phase === "running" || phase === "cancelling" || phase === "restoring";

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await syncApi.history(15));
      setHistoryError(null);
    } catch (e) {
      // details are in the server log; the UI names the cause only when it is something the
      // administrator must fix (database migration missing), otherwise a friendly message
      setHistoryError(e instanceof ApiError && e.code === "schema_outdated" ? "error.schema_outdated" : "history.error");
    }
  }, []);

  // journals of interrupted synchronizations (page reloaded/closed during a run or rollback)
  const loadRecoveries = useCallback(async () => {
    if (!support.supported) return;
    let stored: LocalJournal[] = [];
    try {
      stored = await LocalJournal.listStored();
    } catch {
      return;
    }
    const found: Recovery[] = [];
    for (const journal of stored) {
      if (run.current?.journal?.data.synchronizationId === journal.data.synchronizationId) continue;
      try {
        const details = await syncApi.details(journal.data.synchronizationId);
        if (UNFINISHED.includes(details.status)) found.push({ journal, status: details.status });
        else await journal.discard();
      } catch (error) {
        if (error instanceof ApiError && (error.status === 404 || error.status === 403)) await journal.discard();
      }
    }
    setRecoveries(found);
  }, [support.supported]);

  useEffect(() => {
    void loadHistory();
    void loadRecoveries();
  }, [loadHistory, loadRecoveries]);

  // the folder chosen last time: no need to pick it again (access is re-checked on start)
  useEffect(() => {
    if (!support.supported) return;
    let cancelled = false;
    void restoreFolder().then((handle) => {
      if (handle && !cancelled) setDir((current) => current ?? handle);
    });
    return () => {
      cancelled = true;
    };
  }, [support.supported]);

  // closing the page in the middle would leave half-applied changes behind
  useEffect(() => {
    if (!protectedPhase) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [protectedPhase]);

  // the remote folder may have been deleted in the meantime
  useEffect(() => {
    if (!pathById.has(remoteFolderId) && paths[0]) setRemoteFolderId(defaultFolderId);
  }, [pathById, paths, remoteFolderId, defaultFolderId]);

  function selectFolder(picked: FileSystemDirectoryHandle) {
    setDir(picked);
    void rememberFolder(picked);
    setPlan(null);
    setResult(null);
    setRollback(null);
    setFailure(null);
    setPhase("idle");
  }

  // a dropped folder: no "view and copy files?" question from the browser
  const [dropActive, setDropActive] = useState(false);
  const canDrop = support.supported && !busy;

  function onFolderDrop(event: DragEvent) {
    event.preventDefault();
    setDropActive(false);
    if (!canDrop) return;
    const pending = droppedDirectory(event.dataTransfer); // synchronously, inside the drop event
    if (pending === null) {
      toast.error(t("sync.dropUnsupported"));
      return;
    }
    void pending.then((handle) => (handle ? selectFolder(handle) : toast.error(t("sync.dropNotFolder"))));
  }

  async function chooseFolder() {
    try {
      selectFolder(await pickDirectory());
    } catch (e) {
      if (!(e instanceof PickerCancelled)) toast.error(describeError(t, e));
    }
  }

  async function report(planId: string | null, body: SynchronizationReport): Promise<"ok" | "cancelled"> {
    if (!planId) return "ok";
    try {
      await syncApi.report(planId, body);
      return "ok";
    } catch (e) {
      if (e instanceof ApiError && e.code === "sync_cancelled") return "cancelled";
      toast.error(t("sync.historySaveFailed", { error: describeError(t, e) }));
      return "ok";
    }
  }

  // --- step 1: scan the local folder and ask the backend for a plan ------------------------

  async function start() {
    if (!dir) return;
    setFailure(null);
    setResult(null);
    setRollback(null);
    setPlan(null);
    setCurrent(null);
    setScanCount(0);
    stopRequested.current = false;
    try {
      // only modes that change files on this computer need "edit files" access
      await ensurePermission(dir, needsWriteAccess(mode) ? "readwrite" : "read");
      setPhase("scanning");
      const baseline = loadBaseline(remoteFolderId, dir.name);
      const scanned = await scanDirectory(dir, baseline, setScanCount, () => stopRequested.current);
      for (const path of Object.keys(baseline)) if (!scanned.has(path)) delete baseline[path];
      // cancelled right as the scan finished: no session is created at all
      if (stopRequested.current) throw new ScanCancelled();

      setPhase("planning");
      const newPlan = await syncApi.plan({
        remote_folder_id: remoteFolderId,
        manifest: [...scanned.values()].map((s) => s.entry),
        mode,
        client: "web",
        device: deviceLabel(),
      });
      const actionable = newPlan.changes.some((c) => c.kind !== "UNCHANGED");
      let journal: LocalJournal | null = null;
      if (actionable && newPlan.synchronization_id && !stopRequested.current) {
        journal = await LocalJournal.create(newPlan.synchronization_id, newPlan.remote_folder_id, dir, baseline);
      }
      setPlan(newPlan);
      setStates(newPlan.changes.map((c) => ({ state: c.kind === "UNCHANGED" ? "skipped" : "pending" })));
      run.current = { plan: newPlan, dir, scanned, baseline, journal };
      if (stopRequested.current) {
        // cancelled while the plan was being prepared: close the (empty) session properly
        progressCounts.current = emptyCounts();
        await cancelAndRestore();
        return;
      }

      const deletions = newPlan.changes.filter((c) => c.kind === "DELETE_LOCAL" || c.kind === "DELETE_REMOTE");
      if (deletions.length > 0) setPhase("confirm");
      else await execute();
    } catch (e) {
      if (e instanceof ScanCancelled) {
        // nothing was planned or changed yet
        setPhase("cancelled_early");
        await loadHistory();
        return;
      }
      setFailure(t("sync.failed", { error: describeError(t, e) }));
      setPhase("idle");
    }
  }

  // --- step 2: perform the plan in the browser ------------------------------------------------

  async function execute() {
    const ctx = run.current;
    if (!ctx) return;
    const { plan: current, dir: root, scanned, baseline, journal } = ctx;
    const id = current.synchronization_id;
    const actionable = current.changes.some((c) => c.kind !== "UNCHANGED");

    setPhase("running");
    if (actionable && (await report(id, { ...emptyCounts(), status: "RUNNING" })) === "cancelled") {
      stopRequested.current = true;
    }

    const progress = emptyCounts();
    progressCounts.current = progress;
    let lastBeat = Date.now();
    const executor = new BrowserSyncExecutor(root, current.remote_folder_id, id, scanned, baseline, journal);
    const outcome = await executor.execute(current, {
      shouldStop: () => stopRequested.current,
      onProgress: (index, state, error) => {
        const change = current.changes[index];
        setStates((prev) => prev.map((s, i) => (i === index ? { state, error } : s)));
        if (state === "running" && change) setCurrent(change);
        if (state === "done" && change) progress[COUNT_KEY[change.kind]]++;
        if (state === "failed") progress.failed++;
        // progress report doubles as a heartbeat; a 409 means someone cancelled this sync
        if (id && Date.now() - lastBeat > HEARTBEAT_MS) {
          lastBeat = Date.now();
          void report(id, { ...progress, status: "RUNNING" }).then((r) => {
            if (r === "cancelled") stopRequested.current = true;
          });
        }
      },
    });
    setCurrent(null);

    if (outcome.stopped || stopRequested.current) {
      await cancelAndRestore();
      return;
    }

    saveBaseline(current.remote_folder_id, root.name, baseline);
    if (actionable) {
      const final = await report(id, {
        ...outcome.counts,
        status: outcome.errors.length ? "FAILED" : "COMPLETED",
        // technical text for the history record, not shown in the UI
        error: outcome.errors.length
          ? outcome.errors.map((e) => `${e.path}: ${technicalMessage(e.error)}`).join("\n").slice(0, 2000)
          : null,
      });
      if (final === "cancelled") {
        // the cancel arrived after the last change: restore everything
        await cancelAndRestore();
        return;
      }
    }
    await journal?.discard();
    setResult(outcome);
    setPhase("done");
    run.current = null;
    await Promise.all([loadHistory(), onSynced()]);
  }

  // --- cancellation = stop + restore the previous state ------------------------------------------

  async function cancelAndRestore() {
    const ctx = run.current;
    const id = ctx?.plan.synchronization_id;
    if (!ctx || !id) return;
    setPhase("cancelling");
    try {
      await requestCancel(id);
      const outcome = await rollbackSynchronization(
        id,
        ctx.dir,
        ctx.journal,
        () => setPhase("restoring"),
        progressCounts.current,
      );
      setRollback(outcome);
      setPhase(outcome.details.status === "CANCELLED" ? "cancelled" : "rollback_failed");
      if (outcome.details.status === "CANCELLED") run.current = null;
    } catch (e) {
      setRollback(null);
      setFailure(describeError(t, e));
      setPhase("rollback_failed");
    }
    await Promise.all([loadHistory(), onSynced()]);
  }

  /** Button: during execution the executor stops after the current change, then the rollback runs. */
  async function onCancelClick() {
    stopRequested.current = true;
    if (phase === "scanning" || phase === "planning") {
      setPhase("cancelling"); // start() notices the stop
      return;
    }
    if (phase === "running") {
      setPhase("cancelling");
      const id = run.current?.plan.synchronization_id;
      if (id) await requestCancel(id).catch(() => undefined); // the server refuses further changes at once
      return; // execute() notices the stop and runs cancelAndRestore()
    }
    progressCounts.current = emptyCounts();
    await cancelAndRestore(); // confirm dialog: nothing was executed yet
  }

  async function resume(recovery: Recovery, withLocal: boolean) {
    const id = recovery.journal.data.synchronizationId;
    let root: FileSystemDirectoryHandle | null = null;
    if (withLocal) {
      root = (await handleStore.load(id).catch(() => undefined)) ?? null;
      if (root) {
        try {
          await ensureWritePermission(root);
        } catch (e) {
          toast.error(describeError(t, e));
          return;
        }
      }
    }
    run.current = null;
    setPlan(null);
    setResult(null);
    setFailure(null);
    setPhase("cancelling");
    try {
      await requestCancel(id);
      const outcome = await rollbackSynchronization(id, root, recovery.journal, () => setPhase("restoring"));
      setRollback(outcome);
      setPhase(outcome.details.status === "CANCELLED" ? "cancelled" : "rollback_failed");
      if (outcome.details.status !== "CANCELLED" && !withLocal) await recovery.journal.discard();
    } catch (e) {
      setFailure(describeError(t, e));
      setPhase("rollback_failed");
    }
    await Promise.all([loadHistory(), loadRecoveries(), onSynced()]);
  }

  /** A failed restore the user accepts as it is: forget its local journal and backups. */
  async function dismiss(recovery: Recovery) {
    await recovery.journal.discard();
    setRecoveries((list) => list.filter((r) => r !== recovery));
  }

  const counts = useMemo(() => {
    const c: Partial<Record<ChangeKind, number>> = {};
    plan?.changes.forEach((change) => (c[change.kind] = (c[change.kind] ?? 0) + 1));
    return c;
  }, [plan]);

  const deletionCount = (counts.DELETE_LOCAL ?? 0) + (counts.DELETE_REMOTE ?? 0);
  const doneCount = states.filter((s) => s.state === "done" || s.state === "failed").length;
  const actionableCount = plan ? plan.changes.length - (counts.UNCHANGED ?? 0) : 0;
  const percent = actionableCount ? Math.round((doneCount / actionableCount) * 100) : 0;
  const canCancel = Boolean(run.current?.plan.synchronization_id);

  return (
    <div className="page sync-page">
      <header className="page-head">
        <div>
          <h1>{t("sync.title")}</h1>
          <p className="muted">{t("sync.intro")}</p>
        </div>
      </header>

      {!support.supported && (
        <div className="alert alert-warning">
          <Icon name="alert" />
          <div>
            <strong>{t("sync.unsupported.title")}</strong>
            <div>{t(support.reason === "insecure" ? "sync.unsupported.insecure" : "sync.unsupported.api")}</div>
          </div>
        </div>
      )}

      {recoveries.map((recovery) => {
        const failed = recovery.status === "ROLLBACK_FAILED";
        const folder = recovery.journal.data.folderName;
        return (
          <div
            key={recovery.journal.data.synchronizationId}
            className={`alert ${failed ? "alert-error" : "alert-warning"} recovery`}
            data-status={recovery.status}
            role="alert"
          >
            <Icon name="alert" />
            <div className="alert-body column">
              <strong>{t(failed ? "sync.recovery.failedTitle" : "sync.recovery.title")}</strong>
              <span>{t(failed ? "sync.recovery.failedText" : "sync.recovery.text", { folder })}</span>
              <div className="row">
                <button className="button primary compact" disabled={busy} onClick={() => void resume(recovery, true)}>
                  {t(failed ? "sync.rollbackRetry" : "sync.recovery.action")}
                </button>
                {failed ? (
                  <button className="button ghost compact" disabled={busy} onClick={() => void dismiss(recovery)}>
                    {t("sync.recovery.dismiss")}
                  </button>
                ) : (
                  <button className="button ghost compact" disabled={busy} onClick={() => void resume(recovery, false)}>
                    {t("sync.recovery.remoteOnly")}
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })}

      <div className="sync-grid">
        <section className="card sync-setup">
          <ol className="steps">
            <li>
              <span className="step-no">1</span>
              <div
                className={`step-body folder-drop ${dropActive ? "drop-active" : ""}`}
                onDragOver={(e) => {
                  if (!canDrop || !e.dataTransfer.types.includes("Files")) return;
                  e.preventDefault();
                  setDropActive(true);
                }}
                onDragLeave={() => setDropActive(false)}
                onDrop={onFolderDrop}
              >
                <h3>{t("sync.step.local")}</h3>
                <div className="picker-row">
                  <div className={`picked ${dir ? "" : "empty"}`}>
                    <Icon name="laptop" />
                    <span className="truncate">{dir ? dir.name : t("sync.noFolder")}</span>
                  </div>
                  <button
                    className="button secondary"
                    onClick={() => void chooseFolder()}
                    disabled={!support.supported || busy}
                  >
                    {t(dir ? "sync.change" : "sync.choose")}
                  </button>
                </div>
                {canDrop && (
                  <small className="muted drop-hint-text">
                    <Icon name="upload" size={13} /> {dropActive ? t("sync.dropHere") : t("sync.dropFolder")}
                  </small>
                )}
                <small className="muted">{t("sync.privacy")}</small>
                {dir && (
                  <small className="muted">
                    {t(needsWriteAccess(mode) ? "sync.permission.write" : "sync.permission.read")}
                  </small>
                )}
              </div>
            </li>
            <li>
              <span className="step-no">2</span>
              <div className="step-body">
                <h3>{t("sync.step.remote")}</h3>
                <label className="select-wrap block">
                  <span className="visually-hidden">{t("sync.step.remote")}</span>
                  <Icon name="cloud" size={16} />
                  <select value={remoteFolderId} onChange={(e) => setRemoteFolderId(e.target.value)} disabled={busy}>
                    {paths.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.path}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </li>
            <li>
              <span className="step-no">3</span>
              <div className="step-body">
                <h3>{t("sync.step.mode")}</h3>
                <div className="mode-cards" role="radiogroup" aria-label={t("sync.modeGroup")}>
                  {MODES.map((m) => (
                    <label key={m.value} className={`mode-card ${mode === m.value ? "active" : ""}`}>
                      <input
                        type="radio"
                        name="mode"
                        value={m.value}
                        checked={mode === m.value}
                        onChange={() => setMode(m.value)}
                        disabled={busy}
                      />
                      <Icon name={m.icon} />
                      <span>
                        <strong>{t(`sync.mode.${m.value}.title`)}</strong>
                        <small>{t(`sync.mode.${m.value}.text`)}</small>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </li>
          </ol>
          <div className="sync-start">
            <button
              className="button primary large"
              onClick={() => void start()}
              disabled={!support.supported || !dir || busy}
            >
              <Icon name="sync" className={busy ? "spin" : ""} />
              {phase === "scanning"
                ? t("sync.scanning", { count: scanCount })
                : phase === "planning"
                  ? t("sync.planning")
                  : t("sync.start")}
            </button>
            <small className="muted">{t("sync.conflictRule")}</small>
          </div>
        </section>

        <section className="card sync-result">
          <div className="card-head">
            <h2>{t("sync.result.title")}</h2>
            {plan && (
              <label className="switch">
                <input type="checkbox" checked={hideUnchanged} onChange={(e) => setHideUnchanged(e.target.checked)} />
                {t("sync.hideUnchanged")}
              </label>
            )}
          </div>

          {(phase === "scanning" || phase === "planning" || phase === "running" || phase === "cancelling" ||
            phase === "restoring") && (
            <div className="run-panel" data-phase={phase}>
              <div className="run-head">
                <strong>
                  {phase === "scanning"
                    ? t("sync.scanning", { count: scanCount })
                    : phase === "planning"
                      ? t("sync.planning")
                      : phase === "running"
                        ? t("sync.running", { done: doneCount, total: actionableCount })
                        : phase === "cancelling"
                          ? t("sync.cancelling")
                          : t("sync.restoring")}
                </strong>
                {phase === "running" && (
                  <span className="muted small">{t("sync.progress", { percent, done: doneCount, total: actionableCount })}</span>
                )}
              </div>
              <div className={`progress large ${phase !== "running" ? "indeterminate" : ""}`}>
                <div style={{ width: `${phase === "running" ? percent : 100}%` }} />
              </div>
              {phase === "running" && current && current.kind !== "UNCHANGED" && (
                <div className="run-current muted small">{t(`sync.current.${current.kind}`, { name: current.relative_path })}</div>
              )}
              {(phase === "scanning" || phase === "planning") && (
                <button className="button danger-outline" onClick={() => void onCancelClick()}>
                  <Icon name="x" size={16} /> {t("sync.cancel")}
                </button>
              )}
              {phase === "running" &&
                (canCancel ? (
                  <button className="button danger-outline" onClick={() => void onCancelClick()}>
                    <Icon name="x" size={16} /> {t("sync.cancel")}
                  </button>
                ) : (
                  <small className="muted">{t("sync.cancelUnavailable")}</small>
                ))}
            </div>
          )}

          {failure && (
            <div className="alert alert-error inset">
              <Icon name="alert" /> {failure}
            </div>
          )}

          {phase === "cancelled_early" && (
            <div className="alert alert-success inset" role="status">
              <Icon name="check" />
              <strong>{t("sync.cancelledBeforeStart")}</strong>
            </div>
          )}

          {phase === "cancelled" && (
            <div className="alert alert-success inset" role="status">
              <Icon name="check" />
              <strong>{t("sync.cancelledRestored")}</strong>
            </div>
          )}

          {phase === "rollback_failed" && (
            <div className="alert alert-error inset" role="alert">
              <Icon name="alert" />
              <div className="alert-body column">
                <strong>{t("sync.rollbackFailed")}</strong>
                {rollback && rollback.failures.length > 0 && (
                  <>
                    <span>{t("sync.rollbackFailed.list")}</span>
                    <ul className="failure-list">
                      {rollback.failures.map((f, i) => (
                        <li key={i}>
                          <code>{f.relative_path ?? "-"}</code> · {t(`sync.side.${f.side}`)} · {opLabel(t, f.operation)}:{" "}
                          {describeError(t, new CodedError(f.code))}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {run.current && (
                  <div className="row">
                    <button className="button secondary compact" onClick={() => void cancelAndRestore()}>
                      {t("sync.rollbackRetry")}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {result && phase === "done" && (
            <div className={`alert ${result.errors.length ? "alert-error" : "alert-success"} inset`}>
              <Icon name={result.errors.length ? "alert" : "check"} />
              <div>
                <strong>{t(result.errors.length ? "sync.result.errors" : "sync.result.ok")}</strong>
                <div>{summarize(t, result.counts)}</div>
              </div>
            </div>
          )}

          {plan && (
            <div className="chips">
              {(Object.keys(KIND_META) as ChangeKind[]).map((kind) =>
                counts[kind] ? (
                  <span key={kind} className={`chip tone-${KIND_META[kind].tone}`}>
                    <Icon name={KIND_META[kind].icon} size={14} /> {t(`sync.kind.${kind}`)}: {counts[kind]}
                  </span>
                ) : null,
              )}
            </div>
          )}

          {!plan && !failure && phase !== "cancelled" && phase !== "rollback_failed" && !protectedPhase && (
            <div className="empty-state compact">
              <span className="empty-illustration">
                <Icon name="sync" size={30} />
              </span>
              <strong>{t("sync.empty.title")}</strong>
              <span className="muted">{t("sync.empty.text")}</span>
            </div>
          )}

          {plan && (
            <div className="table-scroll">
              <table className="plan-table">
                <thead>
                  <tr>
                    <th>{t("sync.col.path")}</th>
                    <th>{t("sync.col.action")}</th>
                    <th>{t("sync.col.local")}</th>
                    <th>{t("sync.col.remote")}</th>
                    <th>{t("sync.col.status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.changes.map((change, i) => {
                    if (hideUnchanged && change.kind === "UNCHANGED") return null;
                    const meta = KIND_META[change.kind];
                    const state = states[i];
                    return (
                      <tr key={change.relative_path}>
                        <td className="path-cell" title={change.relative_path}>
                          {change.relative_path}
                        </td>
                        <td>
                          <span className={`chip tone-${meta.tone}`}>
                            <Icon name={meta.icon} size={13} /> {t(`sync.kind.${change.kind}`)}
                          </span>
                        </td>
                        <td className="muted nowrap small" title={format.dateTime(change.local_modified_at)}>
                          {change.local_modified_at ? (
                            <>
                              {format.shortDateTime(change.local_modified_at)}
                              <br />
                              {format.size(change.local_size)}
                            </>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td className="muted nowrap small" title={format.dateTime(change.remote_modified_at)}>
                          {change.remote_modified_at ? (
                            <>
                              {format.shortDateTime(change.remote_modified_at)}
                              <br />
                              {format.size(change.remote_size)}
                            </>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td className="nowrap">
                          <StateBadge state={state?.state ?? "pending"} error={state?.error} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {hideUnchanged && plan.changes.length > 0 && actionableCount === 0 && (
                <p className="muted center small">{t("sync.upToDate")}</p>
              )}
            </div>
          )}
        </section>
      </div>

      <section className="card history-card">
        <div className="card-head">
          <h2>
            <Icon name="history" /> {t("history.title")}
          </h2>
          <button
            className="icon-button"
            onClick={() => void loadHistory()}
            title={t("history.refresh")}
            aria-label={t("history.refresh")}
          >
            <Icon name="refresh" />
          </button>
        </div>
        {historyFailed && (
          <div className="alert alert-error inset" role="alert">
            <Icon name="alert" /> {t(historyError)}
          </div>
        )}
        {!historyFailed && history === null && (
          <div className="table-skeleton">
            <div className="skeleton row" />
          </div>
        )}
        {!historyFailed && history?.length === 0 && <p className="muted inset">{t("history.empty")}</p>}
        {!historyFailed && history && history.length > 0 && (
          <div className="table-scroll">
            <table className="history-table">
              <thead>
                <tr>
                  <th>{t("history.col.started")}</th>
                  <th>{t("history.col.client")}</th>
                  <th>{t("history.col.device")}</th>
                  <th>{t("history.col.folder")}</th>
                  <th>{t("history.col.mode")}</th>
                  <th>{t("history.col.status")}</th>
                  <th>{t("history.col.summary")}</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id}>
                    <td className="nowrap" title={format.dateTime(h.started_at)}>
                      {format.relative(h.started_at)}
                    </td>
                    <td className="nowrap">
                      <Icon name={h.client === "desktop" ? "laptop" : "cloud"} size={15} /> {clientLabel(t, h.client)}
                    </td>
                    <td className="nowrap" data-col="device">{h.device || t("history.deviceUnknown")}</td>
                    <td>{(h.remote_folder_id && pathById.get(h.remote_folder_id)) ?? t("history.deletedFolder")}</td>
                    <td className="nowrap">{t(`sync.mode.${h.mode}.title`)}</td>
                    <td>
                      <span className={`chip tone-${STATUS_TONE[h.status]}`} data-status={h.status}>
                        {t(`history.status.${h.status}`)}
                      </span>
                    </td>
                    <td className="muted small">{historySummary(t, h)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {phase === "confirm" && (
        <ConfirmDialog
          title={t("sync.confirm.title")}
          message={
            <>
              {t("sync.confirm.text", { count: deletionCount })}{" "}
              {counts.DELETE_LOCAL ? `${t("sync.confirm.local", { count: counts.DELETE_LOCAL })} ` : ""}
              {counts.DELETE_REMOTE ? `${t("sync.confirm.remote", { count: counts.DELETE_REMOTE })} ` : ""}
              {t("sync.confirm.continue")}
            </>
          }
          confirmLabel={t("sync.confirm.action")}
          danger
          onConfirm={() => void execute()}
          onCancel={() => void onCancelClick()}
        />
      )}
    </div>
  );
}

function StateBadge({ state, error }: { state: ChangeState; error?: unknown }) {
  const { t } = useI18n();
  switch (state) {
    case "done":
      return (
        <span className="state state-done">
          <Icon name="check" size={14} /> {t("sync.state.done")}
        </span>
      );
    case "failed": {
      const text = error === undefined ? t("sync.state.failed") : describeError(t, error);
      return (
        <span className="state state-failed" title={text}>
          <Icon name="alert" size={14} /> {text}
        </span>
      );
    }
    case "running":
      return (
        <span className="state state-running">
          <span className="spinner small" /> {t("sync.state.running")}
        </span>
      );
    case "skipped":
      return <span className="state muted">-</span>;
    default:
      return <span className="state muted">{t("sync.state.pending")}</span>;
  }
}
