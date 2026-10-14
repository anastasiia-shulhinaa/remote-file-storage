import { type FormEvent, useEffect, useRef, useState } from "react";
import { authApi } from "../api/client";
import type { Availability } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { useI18n } from "../i18n/I18nProvider";
import type { MessageKey } from "../i18n/messages";
import {
  type AuthPolicy,
  type AuthProblem,
  DEFAULT_POLICY,
  hasSpecial,
  hasUppercase,
  loadAuthPolicy,
  loginProblems,
  registrationProblems,
} from "../lib/authRules";
import { ApiError, describeError, errorCode } from "../lib/errors";
import { navigate } from "../lib/router";

interface AuthPageProps {
  mode: "login" | "register";
}

type AvailabilityState = Availability | "checking" | null;

/** Asks the server (debounced) whether an email / username is still free, while the user types. */
function useAvailability(field: "email" | "username", value: string, enabled: boolean): AvailabilityState {
  const [state, setState] = useState<AvailabilityState>(null);
  useEffect(() => {
    const trimmed = value.trim();
    if (!enabled || !trimmed) {
      setState(null);
      return;
    }
    setState("checking");
    let cancelled = false;
    const timer = window.setTimeout(() => {
      authApi
        .availability({ [field]: trimmed })
        .then((result) => !cancelled && setState(result[field] ?? "unknown"))
        .catch(() => !cancelled && setState("unknown"));
    }, 450);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [field, value, enabled]);
  return state;
}

interface PasswordInputProps {
  value: string;
  onChange: (value: string) => void;
  invalid: boolean;
  autoComplete: string;
}

/** Password field with a button that shows / hides what was typed. */
function PasswordInput({ value, onChange, invalid, autoComplete }: PasswordInputProps) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);
  const label = t(visible ? "auth.password.hide" : "auth.password.show");
  return (
    <div className="password-input">
      <input
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid}
        autoComplete={autoComplete}
        autoCapitalize="none"
        spellCheck={false}
      />
      <button
        type="button"
        className="password-toggle"
        onClick={() => setVisible((v) => !v)}
        aria-pressed={visible}
        aria-label={label}
        title={label}
      >
        <Icon name={visible ? "eyeOff" : "eye"} size={18} />
      </button>
    </div>
  );
}

function AvailabilityNote({ state, field }: { state: AvailabilityState; field: "email" | "username" }) {
  const { t } = useI18n();
  if (state === "checking") return <small className="muted">{t("auth.availability.checking")}</small>;
  if (state === "available") {
    return (
      <small className="field-ok">
        <Icon name="check" size={13} /> {t(`auth.availability.${field}.available`)}
      </small>
    );
  }
  if (state === "taken") {
    return (
      <small className="field-error" role="alert">
        <Icon name="alert" size={13} /> {t(`auth.availability.${field}.taken`)}{" "}
        {field === "email" && <a href="#/login">{t("auth.action.login")}</a>}
      </small>
    );
  }
  return null;
}

export function AuthPage({ mode }: AuthPageProps) {
  const { login, register } = useAuth();
  const { t } = useI18n();
  const [identifier, setIdentifier] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [problems, setProblems] = useState<AuthProblem[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [policy, setPolicy] = useState<AuthPolicy>(DEFAULT_POLICY);
  const previousMode = useRef(mode);

  const isLogin = mode === "login";

  // checked as soon as the value has a valid format (the format itself is reported on submit)
  const normalizedUsername = username.trim().toLowerCase();
  const emailState = useAvailability("email", email, !isLogin && new RegExp(policy.email_pattern).test(email.trim()));
  const usernameState = useAvailability(
    "username",
    normalizedUsername,
    !isLogin && new RegExp(policy.username_pattern).test(normalizedUsername),
  );
  const passwordRules: { key: MessageKey; ok: boolean }[] = [
    { key: "auth.password.rule.length", ok: password.length >= policy.password_min_length },
    ...(policy.password_require_uppercase
      ? [{ key: "auth.password.rule.uppercase" as MessageKey, ok: hasUppercase(password) }]
      : []),
    ...(policy.password_require_special
      ? [{ key: "auth.password.rule.special" as MessageKey, ok: hasSpecial(password) }]
      : []),
  ];

  useEffect(() => {
    void loadAuthPolicy().then(setPolicy);
  }, []);

  // switching login → register keeps what was typed: "anna@x.com" becomes the email, "anna" the username
  useEffect(() => {
    if (previousMode.current === mode) return;
    previousMode.current = mode;
    setError(null);
    setProblems([]);
    setNotice(null);
    if (mode === "register" && identifier) {
      if (identifier.includes("@")) setEmail((v) => v || identifier);
      else setUsername((v) => v || identifier.toLowerCase());
    }
  }, [mode, identifier]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    const found: AuthProblem[] = isLogin
      ? loginProblems(identifier, password)
      : registrationProblems({ email, username, password, passwordConfirm }, policy);
    if (!isLogin && emailState === "taken") found.push("user_exists");
    if (!isLogin && usernameState === "taken") found.push("username_taken");
    setProblems(found);
    if (found.length > 0) return;
    setBusy(true);
    try {
      if (isLogin) {
        await login(identifier.trim(), password);
        navigate({ name: "drive", folderId: null });
      } else {
        const result = await register(email.trim(), username.trim().toLowerCase(), password, passwordConfirm,
          displayName.trim());
        if (result.session) navigate({ name: "drive", folderId: null });
        else setNotice(t("auth.registeredConfirm"));
      }
    } catch (e) {
      // the server lists all form problems it found (same rules): show them like the local ones
      const serverProblems = e instanceof ApiError ? (e.extra.problems as AuthProblem[] | undefined) : undefined;
      if (serverProblems?.length) setProblems(serverProblems);
      else setError(e);
    } finally {
      setBusy(false);
    }
  }

  const problemText = (problem: AuthProblem) => t(`error.${problem}` as MessageKey, { min: policy.password_min_length });
  const code = errorCode(error);
  const messages = problems.length ? problems.map(problemText) : error === null ? [] : [describeError(t, error)];

  return (
    <div className="auth-screen">
      <div className="auth-hero" aria-hidden="true">
        <div className="auth-hero-inner">
          <div className="brand brand-large">
            <span className="brand-mark">
              <Icon name="cloud" size={26} />
            </span>
            {t("app.name")}
          </div>
          <p className="auth-tagline">{t("auth.tagline")}</p>
          <ul className="auth-features">
            <li>
              <Icon name="folder" /> {t("auth.feature.folders")}
            </li>
            <li>
              <Icon name="eye" /> {t("auth.feature.preview")}
            </li>
            <li>
              <Icon name="sync" /> {t("auth.feature.sync")}
            </li>
          </ul>
        </div>
      </div>

      <main className="auth-panel">
        <div className="auth-lang">
          <LanguageSwitch />
        </div>
        <form className="auth-card" onSubmit={submit} noValidate>
          <div className="brand auth-mobile-brand">
            <span className="brand-mark">
              <Icon name="cloud" size={20} />
            </span>
            {t("app.name")}
          </div>
          <h1>{t(isLogin ? "auth.login.title" : "auth.register.title")}</h1>
          <p className="muted">{t(isLogin ? "auth.login.subtitle" : "auth.register.subtitle")}</p>

          {messages.length > 0 && (
            <div className="alert alert-error" role="alert" data-code={problems[0] ?? code ?? undefined}>
              <Icon name="alert" />
              <div className="alert-body column">
                {messages.length === 1 ? (
                  <span>{messages[0]}</span>
                ) : (
                  <ul className="problem-list">
                    {messages.map((message) => (
                      <li key={message}>{message}</li>
                    ))}
                  </ul>
                )}
                {isLogin && code === "user_not_found" && (
                  <button type="button" className="button secondary compact" onClick={() => navigate({ name: "register" })}>
                    {t("auth.action.register")}
                  </button>
                )}
                {!isLogin && code === "user_exists" && (
                  <button type="button" className="button secondary compact" onClick={() => navigate({ name: "login" })}>
                    {t("auth.action.login")}
                  </button>
                )}
              </div>
            </div>
          )}
          {notice && (
            <div className="alert alert-info" role="status">
              <Icon name="info" /> {notice}
            </div>
          )}

          {isLogin ? (
            <label className="field">
              <span>{t("auth.field.identifier")}</span>
              <input
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                aria-invalid={problems.includes("identifier_required")}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus
              />
            </label>
          ) : (
            <>
              <label className="field">
                <span>{t("auth.field.email")}</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={
                    problems.includes("email_required") || problems.includes("invalid_email") || emailState === "taken"
                  }
                  autoComplete="email"
                  autoFocus
                />
                <AvailabilityNote state={emailState} field="email" />
              </label>
              <label className="field">
                <span>{t("auth.field.username")}</span>
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  aria-invalid={
                    problems.includes("username_required") ||
                    problems.includes("invalid_username") ||
                    usernameState === "taken"
                  }
                  maxLength={30}
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                />
                <AvailabilityNote state={usernameState} field="username" />
                <small className="muted">{t("auth.field.usernameHint")}</small>
              </label>
              <label className="field">
                <span>{t("auth.field.displayName")}</span>
                <input
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  maxLength={100}
                  autoComplete="nickname"
                  placeholder={t("auth.field.optional")}
                />
              </label>
            </>
          )}
          <label className="field">
            <span>{t("auth.field.password")}</span>
            <PasswordInput
              value={password}
              onChange={setPassword}
              invalid={problems.some((p) => p.startsWith("password_") && p !== "password_mismatch")}
              autoComplete={isLogin ? "current-password" : "new-password"}
            />
            {!isLogin && (
              <ul className="password-rules" aria-label={t("auth.password.rules")}>
                {passwordRules.map((rule) => (
                  <li key={rule.key} className={rule.ok ? "ok" : ""}>
                    <Icon name={rule.ok ? "check" : "x"} size={14} />
                    {t(rule.key, { min: policy.password_min_length })}
                  </li>
                ))}
              </ul>
            )}
          </label>
          {!isLogin && (
            <label className="field">
              <span>{t("auth.field.passwordConfirm")}</span>
              <PasswordInput
                value={passwordConfirm}
                onChange={setPasswordConfirm}
                invalid={problems.includes("password_mismatch")}
                autoComplete="new-password"
              />
            </label>
          )}

          <button className="button primary block" type="submit" disabled={busy}>
            {busy ? t("auth.action.wait") : t(isLogin ? "auth.action.login" : "auth.action.register")}
          </button>

          <p className="auth-switch">
            {isLogin ? (
              <>
                {t("auth.switch.noAccount")} <a href="#/register">{t("auth.action.register")}</a>
              </>
            ) : (
              <>
                {t("auth.switch.hasAccount")} <a href="#/login">{t("auth.action.login")}</a>
              </>
            )}
          </p>
        </form>
      </main>
    </div>
  );
}
