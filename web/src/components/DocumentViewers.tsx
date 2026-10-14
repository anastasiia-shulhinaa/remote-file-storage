import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n/I18nProvider";
import { Icon } from "./Icon";

const MAX_PDF_PAGES = 20;

function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/**
 * PDF rendered with pdf.js onto canvases (works the same in every modern browser,
 * including mobile ones without a built-in PDF viewer). Loaded on demand.
 */
export function PdfViewer({ base64 }: { base64: string }) {
  const { t } = useI18n();
  const container = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const [pages, setPages] = useState({ shown: 0, total: 0 });

  useEffect(() => {
    let cancelled = false;
    let destroy: (() => void) | undefined;

    (async () => {
      const pdfjs = await import("pdfjs-dist");
      const { default: workerUrl } = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

      const task = pdfjs.getDocument({ data: base64ToBytes(base64) });
      destroy = () => void task.destroy();
      const doc = await task.promise;
      const target = container.current;
      if (cancelled || !target) return;

      const total = doc.numPages;
      const shown = Math.min(total, MAX_PDF_PAGES);
      const width = Math.max(320, target.clientWidth - 32);
      const ratio = window.devicePixelRatio || 1;
      target.replaceChildren();

      for (let number = 1; number <= shown && !cancelled; number++) {
        const page = await doc.getPage(number);
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: (width / base.width) * ratio });
        const canvas = document.createElement("canvas");
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${Math.floor(viewport.width / ratio)}px`;
        canvas.className = "pdf-page";
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", t("preview.pdf.page", { page: number, total }));
        target.appendChild(canvas);
        await page.render({ canvas, viewport }).promise;
      }
      if (!cancelled) {
        setPages({ shown, total });
        setState("ready");
      }
    })().catch(() => {
      if (!cancelled) setState("failed");
    });

    return () => {
      cancelled = true;
      destroy?.();
    };
  }, [base64, t]);

  return (
    <div className="pdf-view">
      {state === "loading" && <div className="skeleton preview-skeleton" aria-label={t("preview.loading")} />}
      {state === "failed" && (
        <div className="alert alert-error">
          <Icon name="alert" /> {t("preview.pdf.failed")}
        </div>
      )}
      {state === "ready" && pages.shown < pages.total && (
        <p className="muted small">{t("preview.pdf.limited", { shown: pages.shown, total: pages.total })}</p>
      )}
      <div ref={container} className="pdf-pages" data-pages={state === "ready" ? pages.shown : undefined} />
    </div>
  );
}

/**
 * DOCX converted to HTML by the server. Shown in a sandboxed iframe without scripts,
 * so nothing inside the document can run code or reach the application.
 */
export function HtmlDocumentViewer({ html }: { html: string }) {
  const { t } = useI18n();
  const doc = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<style>
  body { font: 15px/1.6 "Times New Roman", Georgia, serif; color: #111; background: #fff; margin: 0; padding: 32px 40px; }
  img { max-width: 100%; height: auto; }
  table { border-collapse: collapse; margin: 1em 0; }
  td, th { border: 1px solid #bbb; padding: 4px 8px; vertical-align: top; }
  h1, h2, h3 { font-family: Arial, sans-serif; line-height: 1.3; }
</style></head><body>${html}</body></html>`;
  return (
    <div className="docx-view">
      <p className="muted small">{t("preview.docx.note")}</p>
      <iframe className="docx-frame" sandbox="" srcDoc={doc} title={t("file.previewShort")} />
    </div>
  );
}
