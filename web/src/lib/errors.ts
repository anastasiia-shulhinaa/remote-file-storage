import type { Translate } from "../i18n/I18nProvider";
import { uk, type MessageKey } from "../i18n/messages";

/** An error with a stable machine-readable code (from the API or from the browser side). */
export class CodedError extends Error {
  readonly code: string;

  constructor(code: string, message?: string) {
    super(message ?? code);
    this.name = "CodedError";
    this.code = code;
  }
}

/** A failed REST call. `message` is the technical detail and is never shown to users. */
export class ApiError extends CodedError {
  readonly status: number;
  /** Additional fields of the error response (e.g. problems, password_min_length). */
  readonly extra: Record<string, unknown>;

  constructor(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
    super(code, message);
    this.name = "ApiError";
    this.status = status;
    this.extra = extra;
  }
}

function errorKey(code: string): MessageKey | null {
  const key = `error.${code}`;
  return key in uk ? (key as MessageKey) : null;
}

function keyForStatus(status: number): MessageKey {
  if (status === 0) return "error.network_error";
  if (status === 401) return "error.session_expired";
  if (status === 403) return "error.forbidden";
  if (status === 404) return "error.not_found";
  if (status === 413) return "error.file_too_large";
  if (status === 422 || status === 400) return "error.validation_error";
  if (status >= 500) return "error.server";
  return "error.generic";
}

function keyForDomException(error: DOMException): MessageKey {
  switch (error.name) {
    case "NotAllowedError":
    case "SecurityError":
    case "NoModificationAllowedError":
      return "error.local_permission_denied";
    case "NotFoundError":
      return "error.local_not_found";
    case "QuotaExceededError":
      return "error.local_quota";
    default:
      return "error.local_io_error";
  }
}

/** User-facing, translated description of any error. Raw backend text is never shown. */
export function describeError(t: Translate, error: unknown): string {
  if (error instanceof CodedError) {
    const key = errorKey(error.code);
    if (key) {
      const min = error instanceof ApiError ? error.extra.password_min_length : undefined;
      return t(key, typeof min === "number" ? { min } : undefined);
    }
    if (error instanceof ApiError) return t(keyForStatus(error.status));
    return t("error.generic");
  }
  if (error instanceof DOMException) return t(keyForDomException(error));
  if (error instanceof TypeError) return t("error.network_error"); // fetch network failure
  return t("error.generic");
}

/** Technical English text for logs and the synchronization history (not for the UI). */
export function technicalMessage(error: unknown): string {
  if (error instanceof CodedError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return `${error.name}: ${error.message}`;
  return String(error);
}

export function errorCode(error: unknown): string | null {
  return error instanceof CodedError ? error.code : null;
}
