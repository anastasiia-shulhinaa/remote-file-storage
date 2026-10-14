import type { ColumnSettings, Folder, RemoteFile } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { useFormat } from "../lib/format";
import { columnLabelKey } from "./Controls";
import { fileIcon, Icon } from "./Icon";

interface FileTableProps {
  files: RemoteFile[];
  /** Subfolders shown as the first rows (hidden while a type filter searches the subfolders). */
  folders?: Folder[];
  loading?: boolean;
  columns: ColumnSettings;
  /** Files come from subfolders too: show where each one is. */
  showLocation?: boolean;
  locationLabel?: (file: RemoteFile) => string;
  onOpenLocation?: (file: RemoteFile) => void;
  onOpenFolder?: (folder: Folder) => void;
  onClearFolder?: (folder: Folder) => void;
  onDeleteFolder?: (folder: Folder) => void;
  onPreview: (file: RemoteFile) => void;
  onDownload: (file: RemoteFile) => void;
  onDelete: (file: RemoteFile) => void;
}

export function FileTable({
  files,
  folders = [],
  loading,
  columns,
  showLocation = false,
  locationLabel,
  onOpenLocation,
  onOpenFolder,
  onClearFolder,
  onDeleteFolder,
  onPreview,
  onDownload,
  onDelete,
}: FileTableProps) {
  const { t } = useI18n();
  const format = useFormat();
  const empty = <td className="muted">—</td>;
  return (
    <div className={`table-scroll ${loading ? "loading" : ""}`} aria-busy={loading}>
      <table className="file-table">
        <thead>
          <tr>
            <th className="col-name">{t(columnLabelKey("name"))}</th>
            {showLocation && <th>{t("columns.location")}</th>}
            {columns.size && <th className="num">{t(columnLabelKey("size"))}</th>}
            {columns.created_at && <th>{t(columnLabelKey("created_at"))}</th>}
            {columns.modified_at && <th>{t(columnLabelKey("modified_at"))}</th>}
            {columns.uploaded_by && <th>{t(columnLabelKey("uploaded_by"))}</th>}
            {columns.modified_by && <th>{t(columnLabelKey("modified_by"))}</th>}
            <th className="col-actions">
              <span className="visually-hidden">{t("columns.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {folders.map((folder) => (
            <tr key={`folder-${folder.id}`} className="folder-row" onDoubleClick={() => onOpenFolder?.(folder)}>
              <td className="col-name">
                <button
                  className="file-name"
                  onClick={() => onOpenFolder?.(folder)}
                  title={t("folder.open", { name: folder.name })}
                >
                  <span className="file-icon tone-folder">
                    <Icon name="folder" size={17} />
                  </span>
                  <span className="truncate">{folder.name}</span>
                </button>
              </td>
              {showLocation && empty}
              {columns.size && <td className="num muted">—</td>}
              {columns.created_at && (
                <td className="muted nowrap" title={format.relative(folder.created_at)}>
                  {format.dateTime(folder.created_at)}
                </td>
              )}
              {columns.modified_at && empty}
              {columns.uploaded_by && empty}
              {columns.modified_by && empty}
              <td className="col-actions">
                <div className="row-actions">
                  {onClearFolder && (
                    <button
                      className="icon-button"
                      onClick={() => onClearFolder(folder)}
                      title={t("folder.clearShort")}
                      aria-label={t("folder.clear", { name: folder.name })}
                    >
                      <Icon name="eraser" />
                    </button>
                  )}
                  {onDeleteFolder && (
                    <button
                      className="icon-button danger"
                      onClick={() => onDeleteFolder(folder)}
                      title={t("folder.deleteShort")}
                      aria-label={t("folder.delete", { name: folder.name })}
                    >
                      <Icon name="trash" />
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {files.map((file) => {
            const { icon, tone } = fileIcon(file.extension);
            return (
              <tr key={file.id} onDoubleClick={() => onPreview(file)}>
                <td className="col-name">
                  <button className="file-name" onClick={() => onPreview(file)} title={t("file.preview", { name: file.name })}>
                    <span className={`file-icon ${tone}`}>
                      <Icon name={icon} size={17} />
                    </span>
                    <span className="truncate">{file.name}</span>
                    {file.extension && <span className="ext-badge">{file.extension.slice(1)}</span>}
                  </button>
                </td>
                {showLocation && (
                  <td className="muted">
                    <button
                      className="location-link"
                      onClick={() => onOpenLocation?.(file)}
                      title={t("file.openLocation")}
                    >
                      <Icon name="folder" size={14} />
                      <span className="truncate">{locationLabel?.(file) ?? file.folder_path}</span>
                    </button>
                  </td>
                )}
                {columns.size && <td className="num muted nowrap">{format.size(file.size)}</td>}
                {columns.created_at && (
                  <td className="muted nowrap" title={format.relative(file.created_at)}>
                    {format.dateTime(file.created_at)}
                  </td>
                )}
                {columns.modified_at && (
                  <td className="muted nowrap" title={format.relative(file.modified_at)}>
                    {format.dateTime(file.modified_at)}
                  </td>
                )}
                {columns.uploaded_by && <td className="muted">{file.uploaded_by_name ?? file.uploaded_by}</td>}
                {columns.modified_by && <td className="muted">{file.modified_by_name ?? file.modified_by}</td>}
                <td className="col-actions">
                  <div className="row-actions">
                    <button
                      className="icon-button"
                      onClick={() => onPreview(file)}
                      title={t("file.previewShort")}
                      aria-label={t("file.preview", { name: file.name })}
                    >
                      <Icon name="eye" />
                    </button>
                    <button
                      className="icon-button"
                      onClick={() => onDownload(file)}
                      title={t("file.downloadShort")}
                      aria-label={t("file.download", { name: file.name })}
                    >
                      <Icon name="download" />
                    </button>
                    <button
                      className="icon-button danger"
                      onClick={() => onDelete(file)}
                      title={t("file.deleteShort")}
                      aria-label={t("file.delete", { name: file.name })}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
