import { type DragEvent, type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { fileApi, folderApi } from "../api/client";
import type { ExtensionFilter, Folder, RemoteFile, SortField, SortOrder } from "../api/types";
import { ColumnsMenu, Segmented, SortControl } from "../components/Controls";
import { FileTable } from "../components/FileTable";
import { Icon } from "../components/Icon";
import { ConfirmDialog, Modal } from "../components/Modal";
import { PreviewModal } from "../components/PreviewModal";
import { useToast } from "../components/Toasts";
import { useI18n } from "../i18n/I18nProvider";
import type { ColumnSettingsState } from "../lib/columns";
import { describeError, errorCode } from "../lib/errors";
import { breadcrumbs, folderLabel } from "../lib/folders";
import { navigate, routeHref } from "../lib/router";
import { oneOf, saveBlob, usePreference } from "../lib/storage";
import {
  collectDropped,
  collectFiles,
  collectFromFolderInput,
  type UploadOutcome,
  type UploadSelection,
  uploadSelection,
} from "../lib/upload";

interface UploadJob {
  title: string;
  total: number;
  done: number;
  current: string | null;
  outcome: UploadOutcome | null;
}

interface DrivePageProps {
  folders: Folder[];
  folderId: string;
  reloadFolders: () => Promise<void>;
  /** Owned by the workspace, so it survives navigation between folders. */
  columnSettings: ColumnSettingsState;
}

type Dialog =
  | { kind: "preview"; file: RemoteFile }
  | { kind: "delete-file"; file: RemoteFile }
  | { kind: "delete-folder"; folder: Folder }
  | { kind: "clear-folder"; folder: Folder }
  | { kind: "new-folder" }
  | null;

export function DrivePage({ folders, folderId, reloadFolders, columnSettings }: DrivePageProps) {
  const toast = useToast();
  const { t } = useI18n();
  const [extension, setExtension] = usePreference<ExtensionFilter>("minidrive.filter", "", oneOf("", ".c", ".jpg"));
  const [sort, setSort] = usePreference<SortField>("minidrive.sort", "created_at", oneOf("created_at", "modified_at", "name"));
  const [order, setOrder] = usePreference<SortOrder>("minidrive.order", "desc", oneOf("asc", "desc"));

  const [files, setFiles] = useState<RemoteFile[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [upload, setUpload] = useState<UploadJob | null>(null);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const requestId = useRef(0);

  const rootLabel = t("nav.myDrive");
  const folder = folders.find((f) => f.id === folderId) ?? null;
  const folderName = folder ? folderLabel(folder, rootLabel) : "";
  const crumbs = breadcrumbs(folders, folderId);
  const subfolders = folders
    .filter((f) => f.parent_folder_id === folderId)
    .sort((a, b) => {
      // folders follow the chosen sort too (they have no modification time: creation time is used)
      const byName = a.name.localeCompare(b.name);
      const diff = sort === "name" ? byName : a.created_at.localeCompare(b.created_at) || byName;
      return order === "asc" ? diff : -diff;
    });
  // a type filter searches this folder and all its subfolders
  const recursive = extension !== "";
  const filters: { value: ExtensionFilter; label: string }[] = [
    { value: "", label: t("filter.all") },
    { value: ".c", label: ".c" },
    { value: ".jpg", label: ".jpg" },
  ];
  const { columns, status: columnsStatus, toggle: toggleColumn, setAll: setAllColumns } = columnSettings;

  // --- data -----------------------------------------------------------------------

  const loadFiles = useCallback(async () => {
    // only the latest request may update the table (fast filter switching)
    const id = ++requestId.current;
    setLoading(true);
    setLoadError(null);
    try {
      const list = await fileApi.list({ folderId, extension, sort, order, recursive: extension !== "" });
      if (id === requestId.current) setFiles(list);
    } catch (e) {
      if (id === requestId.current) {
        setFiles([]);
        setLoadError(e);
      }
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [folderId, extension, sort, order]);

  // the previous rows stay visible (dimmed) while a new filter/sort loads
  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  /** Folders and files: picks up changes made elsewhere (desktop client, another tab). */
  const refreshAll = useCallback(async () => {
    await Promise.all([reloadFolders(), loadFiles()]);
  }, [reloadFolders, loadFiles]);

  // coming back to this tab/window refreshes the view (at most every few seconds)
  const lastRefresh = useRef(Date.now());
  useEffect(() => {
    const onReturn = () => {
      if (document.visibilityState !== "visible" || Date.now() - lastRefresh.current < 5000) return;
      lastRefresh.current = Date.now();
      void refreshAll();
    };
    window.addEventListener("focus", onReturn);
    document.addEventListener("visibilitychange", onReturn);
    return () => {
      window.removeEventListener("focus", onReturn);
      document.removeEventListener("visibilitychange", onReturn);
    };
  }, [refreshAll]);

  // --- upload ---------------------------------------------------------------------

  // the folder picker attribute is not part of the standard input typings
  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  const uploading = upload !== null && upload.outcome === null;

  /** Files and folders: structure preserved, every failure listed (nothing skipped silently). */
  async function runUpload(selection: UploadSelection) {
    if (selection.items.length === 0 && selection.dirs.length === 0) return;
    const isFolder = selection.dirs.length > 0;
    const title = isFolder
      ? t("drive.uploadPanel.folder", { name: selection.roots.join(", ") })
      : t("drive.uploadPanel.files");
    const existing = new Set((files ?? []).map((f) => f.name));
    setUpload({ title, total: selection.items.length, done: 0, current: null, outcome: null });

    const outcome = await uploadSelection(selection, folderId, existing, (progress) =>
      setUpload((job) => (job ? { ...job, done: progress.done, current: progress.current } : job)),
    );

    // a single plain file: a short toast is enough; otherwise keep the summary panel open
    const single = !isFolder && selection.items.length === 1;
    if (single && outcome.failures.length === 0) {
      const name = selection.items[0]?.file.name ?? "";
      toast.success(t(outcome.replaced ? "drive.toast.replaced" : "drive.toast.uploaded", { name }));
      setUpload(null);
    } else {
      setUpload((job) => (job ? { ...job, done: job.total, current: null, outcome } : job));
    }
    if (isFolder) await reloadFolders();
    await loadFiles();
  }

  function onDragEnter(e: DragEvent) {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    dragDepth.current++;
    setDragging(true);
  }

  function onDragLeave() {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    const pending = collectDropped(e.dataTransfer); // must run synchronously inside the drop event
    if (pending === null) {
      toast.error(t("drive.dropNoFolders"));
      void runUpload(collectFiles(Array.from(e.dataTransfer.files)));
      return;
    }
    void pending.then(runUpload);
  }

  // --- file actions ---------------------------------------------------------------

  async function download(file: RemoteFile) {
    try {
      saveBlob(await fileApi.download(file.id), file.name);
    } catch (e) {
      toast.error(t("drive.toast.downloadFailed", { error: describeError(t, e) }));
    }
  }

  async function deleteFile(file: RemoteFile) {
    setBusy(true);
    try {
      await fileApi.remove(file.id);
      toast.success(t("drive.toast.deleted", { name: file.name }));
      setDialog(null);
      await loadFiles();
    } catch (e) {
      toast.error(t("drive.toast.deleteFailed", { name: file.name, error: describeError(t, e) }));
    } finally {
      setBusy(false);
    }
  }

  async function deleteFolder(target: Folder) {
    setBusy(true);
    try {
      await folderApi.remove(target.id);
      toast.success(t("drive.toast.folderDeleted", { name: target.name }));
      setDialog(null);
      await reloadFolders();
      navigate({ name: "drive", folderId: target.parent_folder_id });
    } catch (e) {
      toast.error(t("drive.toast.folderDeleteFailed", { error: describeError(t, e) }));
    } finally {
      setBusy(false);
    }
  }

  async function clearFolder(target: Folder) {
    setBusy(true);
    try {
      const result = await folderApi.clear(target.id);
      toast.success(
        t("drive.toast.folderCleared", {
          name: folderLabel(target, rootLabel),
          files: result.deleted_files,
          folders: result.deleted_folders,
        }),
      );
      setDialog(null);
      await refreshAll();
    } catch (e) {
      toast.error(t("drive.toast.folderClearFailed", { error: describeError(t, e) }));
    } finally {
      setBusy(false);
    }
  }

  async function createFolder(name: string): Promise<unknown> {
    try {
      const created = await folderApi.create(name, folderId);
      await reloadFolders();
      setDialog(null);
      toast.success(t("drive.toast.folderCreated", { name: created.name }));
      return null;
    } catch (e) {
      return e;
    }
  }

  // --- render ---------------------------------------------------------------------

  if (!folder && folders.length > 0) {
    return (
      <div className="page">
        <div className="empty-state">
          <Icon name="alert" size={32} />
          <strong>{t("drive.notFound.title")}</strong>
          <a className="button primary" href={routeHref({ name: "drive", folderId: null })}>
            {t("drive.notFound.action")}
          </a>
        </div>
      </div>
    );
  }

  const isRoot = folder?.parent_folder_id === null;
  const filterLabel = filters.find((f) => f.value === extension)?.label ?? "";

  return (
    <div
      className={`page drive-page ${dragging ? "dragging" : ""}`}
      onDragEnter={onDragEnter}
      onDragOver={(e) => e.dataTransfer.types.includes("Files") && e.preventDefault()}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <header className="page-head">
        <nav className="breadcrumbs" aria-label={t("nav.folders")}>
          {crumbs.map((crumb, i) =>
            i < crumbs.length - 1 ? (
              <span key={crumb.id} className="crumb">
                <a href={routeHref({ name: "drive", folderId: crumb.id })}>{folderLabel(crumb, rootLabel)}</a>
                <Icon name="chevronRight" size={14} />
              </span>
            ) : (
              <h1 key={crumb.id} className="crumb current">
                {folderLabel(crumb, rootLabel)}
              </h1>
            ),
          )}
        </nav>
        <div className="page-actions">
          {folder && (
            <button className="button ghost danger-text" onClick={() => setDialog({ kind: "clear-folder", folder })}>
              <Icon name="eraser" size={16} /> {t("drive.clearFolder")}
            </button>
          )}
          {!isRoot && folder && (
            <button className="button ghost danger-text" onClick={() => setDialog({ kind: "delete-folder", folder })}>
              <Icon name="trash" size={16} /> {t("drive.deleteFolder")}
            </button>
          )}
          <button className="button secondary" onClick={() => setDialog({ kind: "new-folder" })}>
            <Icon name="folderPlus" size={16} /> {t("drive.newFolder")}
          </button>
          <button className="button secondary" onClick={() => folderInput.current?.click()} disabled={uploading}>
            <Icon name="folder" size={16} /> {t("drive.uploadFolder")}
          </button>
          <button className="button primary" onClick={() => fileInput.current?.click()} disabled={uploading}>
            <Icon name="upload" size={16} /> {t("drive.upload")}
          </button>
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              void runUpload(collectFiles(Array.from(e.target.files ?? [])));
              e.target.value = "";
            }}
          />
          <input
            ref={folderInput}
            type="file"
            multiple
            hidden
            data-testid="folder-input"
            onChange={(e) => {
              if (e.target.files) void runUpload(collectFromFolderInput(e.target.files));
              e.target.value = "";
            }}
          />
        </div>
      </header>

      {upload && (
        <div className="upload-panel card" role="status" data-finished={upload.outcome !== null}>
          <div className="upload-panel-head">
            {upload.outcome === null ? <div className="spinner" /> : <Icon name={upload.outcome.failures.length ? "alert" : "check"} />}
            <strong className="truncate">{upload.title}</strong>
            <span className="muted small">{t("drive.uploadPanel.progress", { done: upload.done, total: upload.total })}</span>
            {upload.outcome !== null && (
              <button className="icon-button" onClick={() => setUpload(null)} aria-label={t("drive.uploadPanel.close")}>
                <Icon name="x" />
              </button>
            )}
          </div>
          <div className="progress">
            <div style={{ width: `${upload.total ? (upload.done / upload.total) * 100 : 100}%` }} />
          </div>
          {upload.current && (
            <div className="muted small truncate">{t("drive.uploadPanel.current", { name: upload.current })}</div>
          )}
          {upload.outcome && (
            <>
              <div className="small">
                {t("drive.uploadPanel.done", { uploaded: upload.outcome.uploaded, folders: upload.outcome.foldersCreated })}
              </div>
              {upload.outcome.failures.length > 0 && (
                <div className="upload-failures">
                  <strong className="small">{t("drive.uploadPanel.failed", { count: upload.outcome.failures.length })}</strong>
                  <ul className="failure-list">
                    {upload.outcome.failures.map((f) => (
                      <li key={f.path}>
                        <code>{f.path}</code>: {describeError(t, f.error)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <section className="section">
        <div className="toolbar">
          <h2 className="section-title">{t("drive.files")}</h2>
          <div className="toolbar-controls">
            <Segmented label={t("filter.label")} value={extension} options={filters} onChange={setExtension} />
            <SortControl
              sort={sort}
              order={order}
              onChange={(s, o) => {
                setSort(s);
                setOrder(o);
              }}
            />
            <ColumnsMenu columns={columns} status={columnsStatus} onToggle={toggleColumn} onSetAll={setAllColumns} />
            <button
              className="icon-button"
              onClick={() => void refreshAll()}
              title={t("drive.refresh")}
              aria-label={t("drive.refresh")}
            >
              <Icon name="refresh" />
            </button>
          </div>
        </div>

        <div className="card">
          {loadError !== null && (
            <div className="alert alert-error inset">
              <Icon name="alert" /> {describeError(t, loadError)}
              <button className="button ghost compact" onClick={() => void loadFiles()}>
                {t("drive.retry")}
              </button>
            </div>
          )}
          {files === null ? (
            <div className="table-skeleton" aria-label={t("drive.loadingFiles")}>
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="skeleton row" />
              ))}
            </div>
          ) : files.length === 0 && (recursive || subfolders.length === 0) && loadError === null ? (
            <div className="empty-state">
              <span className="empty-illustration">
                <Icon name={extension ? "filter" : "cloud"} size={34} />
              </span>
              {extension ? (
                <>
                  <strong>{t("drive.emptyFiltered.title", { filter: filterLabel })}</strong>
                  <button className="button ghost compact" onClick={() => setExtension("")}>
                    {t("drive.showAll")}
                  </button>
                </>
              ) : (
                <>
                  <strong>{t("drive.empty.title")}</strong>
                  <span className="muted">{t("drive.empty.text")}</span>
                </>
              )}
            </div>
          ) : (
            <FileTable
              files={files}
              folders={recursive ? [] : subfolders}
              loading={loading}
              columns={columns}
              showLocation={recursive}
              locationLabel={(file) => (file.folder_path ? `${folderName}/${file.folder_path}` : folderName)}
              onOpenLocation={(file) => navigate({ name: "drive", folderId: file.folder_id })}
              onOpenFolder={(sub) => navigate({ name: "drive", folderId: sub.id })}
              onClearFolder={(sub) => setDialog({ kind: "clear-folder", folder: sub })}
              onDeleteFolder={(sub) => setDialog({ kind: "delete-folder", folder: sub })}
              onPreview={(file) => setDialog({ kind: "preview", file })}
              onDownload={(file) => void download(file)}
              onDelete={(file) => setDialog({ kind: "delete-file", file })}
            />
          )}
        </div>
        <p className="hint">
          <Icon name="info" size={14} /> {t(recursive ? "drive.hintRecursive" : "drive.hint")}
        </p>
      </section>

      <div className="drop-overlay" aria-hidden={!dragging}>
        <div>
          <Icon name="upload" size={36} />
          <strong>{t("drive.drop", { folder: folderName })}</strong>
        </div>
      </div>

      {dialog?.kind === "preview" && (
        <PreviewModal file={dialog.file} onClose={() => setDialog(null)} onDownload={(f) => void download(f)} />
      )}
      {dialog?.kind === "delete-file" && (
        <ConfirmDialog
          title={t("dialog.deleteFile.title")}
          message={t("dialog.deleteFile.text", { name: dialog.file.name })}
          confirmLabel={t("dialog.deleteFile.confirm")}
          danger
          busy={busy}
          onConfirm={() => void deleteFile(dialog.file)}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "delete-folder" && (
        <ConfirmDialog
          title={t("dialog.deleteFolder.title")}
          message={t("dialog.deleteFolder.text", { name: dialog.folder.name })}
          confirmLabel={t("dialog.deleteFolder.confirm")}
          danger
          busy={busy}
          onConfirm={() => void deleteFolder(dialog.folder)}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "clear-folder" && (
        <ConfirmDialog
          title={t("dialog.clearFolder.title")}
          message={t("dialog.clearFolder.text", { name: folderLabel(dialog.folder, rootLabel) })}
          confirmLabel={t("dialog.clearFolder.confirm")}
          danger
          busy={busy}
          onConfirm={() => void clearFolder(dialog.folder)}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "new-folder" && (
        <NewFolderDialog parentName={folderName} onCreate={createFolder} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}

interface NewFolderDialogProps {
  parentName: string;
  /** Resolves to null on success, or to the error. */
  onCreate: (name: string) => Promise<unknown>;
  onClose: () => void;
}

function NewFolderDialog({ parentName, onCreate, onClose }: NewFolderDialogProps) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(await onCreate(trimmed));
    setBusy(false);
  }

  return (
    <Modal title={t("dialog.newFolder.title")} onClose={onClose}>
      <form onSubmit={submit} className="stack">
        <label className="field">
          <span>{t("dialog.newFolder.name")}</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={255} autoFocus required />
          <small className="muted">{t("dialog.newFolder.inside", { parent: parentName })}</small>
        </label>
        {error !== null && (
          <div className="alert alert-error" data-code={errorCode(error) ?? undefined}>
            <Icon name="alert" /> {describeError(t, error)}
          </div>
        )}
        <div className="modal-actions">
          <button type="button" className="button ghost" onClick={onClose}>
            {t("dialog.cancel")}
          </button>
          <button type="submit" className="button primary" disabled={busy || !name.trim()}>
            {busy ? t("dialog.newFolder.creating") : t("dialog.newFolder.create")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
