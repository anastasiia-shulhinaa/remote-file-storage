import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { en, type MessageKey, uk } from "./messages";

export type Lang = "uk" | "en";

const DICTIONARIES: Record<Lang, Record<MessageKey, string>> = { uk, en };
const LOCALES: Record<Lang, string> = { uk: "uk-UA", en: "en-GB" };
const STORAGE_KEY = "minidrive.lang";

export type Params = Record<string, string | number>;
export type Translate = (key: MessageKey, params?: Params) => string;

interface I18n {
  lang: Lang;
  /** BCP 47 locale for Intl formatting (dates, numbers). */
  locale: string;
  setLang: (lang: Lang) => void;
  t: Translate;
}

const I18nContext = createContext<I18n | null>(null);

function readStoredLang(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "en" || stored === "uk" ? stored : "uk";
  } catch {
    return "uk";
  }
}

export function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStoredLang);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* storage unavailable: the choice lasts for this page only */
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const value = useMemo<I18n>(() => {
    const dictionary = DICTIONARIES[lang];
    return {
      lang,
      locale: LOCALES[lang],
      setLang,
      t: (key, params) => interpolate(dictionary[key], params),
    };
  }, [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
