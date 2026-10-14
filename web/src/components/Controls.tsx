import { type ReactNode, useEffect, useRef, useState } from "react";
import type { ColumnSettings, OptionalColumn, SortField, SortOrder } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import type { MessageKey } from "../i18n/messages";
import type { ColumnsStatus } from "../lib/columns";
import { Icon } from "./Icon";

// --- segmented control -----------------------------------------------------------
// Every option stays clickable at all times, so switching between filters
// (All → .c → .jpg → All …) always works.

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
}

export function Segmented<T extends string>({ label, value, options, onChange }: SegmentedProps<T>) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value || "all"}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          className={option.value === value ? "active" : ""}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// --- sort control ------------------------------------------------------------------

const SORT_FIELDS: SortField[] = ["created_at", "modified_at", "name"];

interface SortControlProps {
  sort: SortField;
  order: SortOrder;
  onChange: (sort: SortField, order: SortOrder) => void;
}

export function SortControl({ sort, order, onChange }: SortControlProps) {
  const { t } = useI18n();
  const ascending = order === "asc";
  const directionLabel =
    sort === "name" ? t(ascending ? "sort.az" : "sort.za") : t(ascending ? "sort.oldest" : "sort.newest");
  return (
    <div className="sort-control">
      <label className="select-wrap">
        <span className="visually-hidden">{t("sort.label")}</span>
        <Icon name="filter" size={15} />
        <select value={sort} onChange={(e) => onChange(e.target.value as SortField, order)}>
          {SORT_FIELDS.map((field) => (
            <option key={field} value={field}>
              {t(`sort.${field}`)}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="button ghost compact"
        onClick={() => onChange(sort, ascending ? "desc" : "asc")}
        title={t("sort.toggle")}
      >
        <Icon name={ascending ? "arrowUp" : "arrowDown"} size={15} />
        {directionLabel}
      </button>
    </div>
  );
}

// --- popover -----------------------------------------------------------------------

interface PopoverProps {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  children: ReactNode;
  align?: "left" | "right";
}

export function Popover({ trigger, children, align = "right" }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !root.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div className="popover-root" ref={root}>
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && <div className={`popover popover-${align}`}>{children}</div>}
    </div>
  );
}

// --- column visibility menu -------------------------------------------------------

export const OPTIONAL_COLUMNS: OptionalColumn[] = ["size", "created_at", "modified_at", "uploaded_by", "modified_by"];

export function columnLabelKey(column: OptionalColumn | "name"): MessageKey {
  return `columns.${column}`;
}

interface ColumnsMenuProps {
  columns: ColumnSettings;
  status: ColumnsStatus;
  onToggle: (column: OptionalColumn) => void;
  onSetAll: (visible: boolean) => void;
}

/** "All": checked when every optional column is shown, half-checked when only some are. */
function AllColumnsCheckbox({ columns, onSetAll }: Pick<ColumnsMenuProps, "columns" | "onSetAll">) {
  const { t } = useI18n();
  const shown = OPTIONAL_COLUMNS.filter((column) => columns[column]).length;
  const all = shown === OPTIONAL_COLUMNS.length;
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (box.current) box.current.indeterminate = shown > 0 && !all;
  }, [shown, all]);
  return (
    <label className="check-row check-all">
      <input ref={box} type="checkbox" checked={all} onChange={() => onSetAll(!all)} />
      {t("columns.all")}
    </label>
  );
}

export function ColumnsMenu({ columns, status, onToggle, onSetAll }: ColumnsMenuProps) {
  const { t } = useI18n();
  return (
    <Popover
      trigger={({ open, toggle }) => (
        <button
          type="button"
          className="button ghost compact"
          aria-expanded={open}
          aria-haspopup="true"
          onClick={toggle}
        >
          <Icon name="columns" size={15} /> {t("columns.button")}
          {status === "local-only" && <span className="dot-warning" aria-hidden="true" />}
        </button>
      )}
    >
      <div className="menu-title">{t("columns.title")}</div>
      <AllColumnsCheckbox columns={columns} onSetAll={onSetAll} />
      <label className="check-row disabled" title={t("columns.nameAlways")}>
        <input type="checkbox" checked disabled /> {t("columns.name")}
        <span className="badge">{t("columns.always")}</span>
      </label>
      {OPTIONAL_COLUMNS.map((column) => (
        <label key={column} className="check-row">
          <input type="checkbox" checked={columns[column]} onChange={() => onToggle(column)} />
          {t(columnLabelKey(column))}
        </label>
      ))}
      {status === "loading" && <div className="menu-note">{t("columns.loading")}</div>}
      {status === "local-only" && <div className="menu-note warning">{t("columns.savedLocally")}</div>}
    </Popover>
  );
}
