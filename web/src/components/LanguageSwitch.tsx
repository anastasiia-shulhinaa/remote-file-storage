import { type Lang, useI18n } from "../i18n/I18nProvider";

const OPTIONS: { value: Lang; label: string }[] = [
  { value: "uk", label: "UA" },
  { value: "en", label: "EN" },
];

export function LanguageSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="segmented lang-switch" role="radiogroup" aria-label={t("lang.label")}>
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={lang === option.value}
          className={lang === option.value ? "active" : ""}
          onClick={() => setLang(option.value)}
          lang={option.value}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
