import { useMemo } from "react";
import { type Lang, useI18n } from "../i18n/I18nProvider";

const SIZE_UNITS: Record<Lang, readonly string[]> = {
  uk: ["Б", "КБ", "МБ", "ГБ"],
  en: ["B", "KB", "MB", "GB"],
};

export function formatSize(bytes: number | null | undefined, lang: Lang, locale: string): string {
  if (bytes == null) return "-";
  const units = SIZE_UNITS[lang];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  const digits = unit === 0 ? 0 : value < 10 ? 1 : 0;
  return `${value.toLocaleString(locale, { maximumFractionDigits: digits })} ${units[unit]}`;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function dateFormatter(locale: string, short: boolean): Intl.DateTimeFormat {
  const key = `${locale}|${short}`;
  let formatter = formatters.get(key);
  if (!formatter) {
    // compact numeric form (07.10.2026, 14:05:09) keeps metadata columns narrow in every language
    formatter = new Intl.DateTimeFormat(locale, {
      ...(short ? {} : { year: "numeric" }),
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    formatters.set(key, formatter);
  }
  return formatter;
}

export function formatDateTime(iso: string | null | undefined, locale: string, short = false): string {
  if (!iso) return "-";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : dateFormatter(locale, short).format(date);
}

export function formatRelative(iso: string | null | undefined, locale: string): string {
  if (!iso) return "-";
  const relative = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["second", 60],
    ["minute", 60],
    ["hour", 24],
    ["day", 30],
    ["month", 12],
    ["year", Number.POSITIVE_INFINITY],
  ];
  let value = (new Date(iso).getTime() - Date.now()) / 1000;
  for (const [unit, size] of steps) {
    if (Math.abs(value) < size) return relative.format(Math.round(value), unit);
    value /= size;
  }
  return formatDateTime(iso, locale);
}

/** Formatting functions bound to the current interface language. */
export function useFormat() {
  const { lang, locale } = useI18n();
  return useMemo(
    () => ({
      size: (bytes: number | null | undefined) => formatSize(bytes, lang, locale),
      dateTime: (iso: string | null | undefined) => formatDateTime(iso, locale),
      shortDateTime: (iso: string | null | undefined) => formatDateTime(iso, locale, true),
      relative: (iso: string | null | undefined) => formatRelative(iso, locale),
    }),
    [lang, locale],
  );
}
