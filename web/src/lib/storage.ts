import { useEffect, useState } from "react";

/** Per-browser UI preference (filter, sort…) kept in localStorage; works without it too. */
export function usePreference<T>(key: string, initial: T, isValid: (value: unknown) => value is T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      const parsed: unknown = raw === null ? initial : JSON.parse(raw);
      return isValid(parsed) ? parsed : initial;
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable */
    }
  }, [key, value]);

  return [value, setValue];
}

export function oneOf<T extends string>(...values: readonly T[]) {
  return (value: unknown): value is T => typeof value === "string" && (values as readonly string[]).includes(value);
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
