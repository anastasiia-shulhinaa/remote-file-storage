import { type ReactNode, useEffect, useRef } from "react";
import { useI18n } from "../i18n/I18nProvider";
import { Icon } from "./Icon";

interface ModalProps {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}

export function Modal({ title, onClose, children, footer, wide }: ModalProps) {
  const { t } = useI18n();
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={panel}
        className={`modal ${wide ? "modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
      >
        <header className="modal-head">
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label={t("dialog.close")}>
            <Icon name="x" />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

interface ConfirmProps {
  title: string;
  message: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ title, message, confirmLabel, danger, busy, onConfirm, onCancel }: ConfirmProps) {
  const { t } = useI18n();
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button className="button ghost" onClick={onCancel} disabled={busy}>
            {t("dialog.cancel")}
          </button>
          <button className={`button ${danger ? "danger" : "primary"}`} onClick={onConfirm} disabled={busy}>
            {busy ? t("dialog.working") : confirmLabel}
          </button>
        </>
      }
    >
      <div className="confirm-message">{message}</div>
    </Modal>
  );
}
