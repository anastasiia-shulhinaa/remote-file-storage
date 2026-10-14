import { useEffect, useState } from "react";
import { fileApi } from "../api/client";
import type { Preview, RemoteFile } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { describeError } from "../lib/errors";
import { useFormat } from "../lib/format";
import { HtmlDocumentViewer, PdfViewer } from "./DocumentViewers";
import { fileIcon, Icon } from "./Icon";
import { Modal } from "./Modal";

interface PreviewModalProps {
  file: RemoteFile;
  onClose: () => void;
  onDownload: (file: RemoteFile) => void;
}

/** FileViewer: metadata + content preview from GET /files/{id}/preview. */
export function PreviewModal({ file, onClose, onDownload }: PreviewModalProps) {
  const { t } = useI18n();
  const format = useFormat();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    setPreview(null);
    setError(null);
    fileApi
      .preview(file.id)
      .then((p) => !cancelled && setPreview(p))
      .catch((e: unknown) => !cancelled && setError(e ?? new Error("preview failed")));
    return () => {
      cancelled = true;
    };
  }, [file.id]);

  const { icon, tone } = fileIcon(file.extension);

  return (
    <Modal
      wide
      onClose={onClose}
      title={
        <span className="preview-title">
          <span className={`file-icon ${tone}`}>
            <Icon name={icon} size={17} />
          </span>
          <span className="truncate">{file.name}</span>
        </span>
      }
      footer={
        <>
          <button className="button ghost" onClick={onClose}>
            {t("dialog.close")}
          </button>
          <button className="button primary" onClick={() => onDownload(file)}>
            <Icon name="download" size={16} /> {t("preview.download")}
          </button>
        </>
      }
    >
      <dl className="meta-grid">
        <div>
          <dt>{t("preview.size")}</dt>
          <dd>{format.size(file.size)}</dd>
        </div>
        <div>
          <dt>{t("preview.created")}</dt>
          <dd>{format.dateTime(file.created_at)}</dd>
        </div>
        <div>
          <dt>{t("preview.modified")}</dt>
          <dd>{format.dateTime(file.modified_at)}</dd>
        </div>
        <div>
          <dt>{t("preview.uploadedBy")}</dt>
          <dd>{file.uploaded_by_name ?? file.uploaded_by}</dd>
        </div>
        <div>
          <dt>{t("preview.modifiedBy")}</dt>
          <dd>{file.modified_by_name ?? file.modified_by}</dd>
        </div>
      </dl>

      <div className="preview-area" data-preview-type={preview?.type}>
        {error !== null && (
          <div className="alert alert-error">
            <Icon name="alert" /> {t("preview.failed", { error: describeError(t, error) })}
          </div>
        )}
        {error === null && !preview && <div className="skeleton preview-skeleton" aria-label={t("preview.loading")} />}

        {preview?.type === "text" && (
          <>
            <div className="code-head">
              <span className="chip tone-neutral">{t(`preview.lang.${preview.language}`)}</span>
              {preview.truncated && <span className="muted small">{t("preview.truncated")}</span>}
            </div>
            <pre className="code-view">
              <code>
                {preview.content.split("\n").map((line, i) => (
                  <span className="code-line" key={i}>
                    <span className="line-no">{i + 1}</span>
                    {line || " "}
                    {"\n"}
                  </span>
                ))}
              </code>
            </pre>
          </>
        )}

        {preview?.type === "image" && (
          <div className="image-view">
            <img src={`data:${preview.mime_type};base64,${preview.content_base64}`} alt={preview.name} />
          </div>
        )}

        {preview?.type === "pdf" && <PdfViewer base64={preview.content_base64} />}

        {preview?.type === "html" && <HtmlDocumentViewer html={preview.content} />}

        {preview?.type === "unavailable" && (
          <div className="empty-state compact">
            <Icon name="eye" size={28} />
            <strong>{t(`preview.unavailable.${preview.reason ?? "unsupported_type"}`)}</strong>
            <span className="muted">{t("preview.supported")}</span>
          </div>
        )}
      </div>
    </Modal>
  );
}
