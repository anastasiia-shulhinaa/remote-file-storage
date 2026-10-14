// Client-side check of the login / registration form. The rules are the backend's
// (GET /auth/config, app/core/auth_policy.py); the backend checks them again.

import { authApi } from "../api/client";

export interface AuthPolicy {
  password_min_length: number;
  password_max_length: number;
  email_pattern: string;
  username_pattern: string;
  username_required: boolean;
  password_require_uppercase: boolean;
  password_require_special: boolean;
}

// used only until /auth/config has answered (same values as the backend defaults)
export const DEFAULT_POLICY: AuthPolicy = {
  password_min_length: 6,
  password_max_length: 72,
  email_pattern: "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$",
  username_pattern: "^[a-z0-9_.-]{3,30}$",
  username_required: true,
  password_require_uppercase: true,
  password_require_special: true,
};

export const hasUppercase = (password: string) => /\p{Lu}/u.test(password);
/** A sign that is neither a letter, a digit nor a space: ! @ # $ % _ - . , etc. */
export const hasSpecial = (password: string) => /[^\p{L}\p{N}\s]/u.test(password);

let cached: Promise<AuthPolicy> | null = null;

export function loadAuthPolicy(): Promise<AuthPolicy> {
  cached ??= authApi.config().catch(() => {
    cached = null; // retry next time; meanwhile use the defaults
    return DEFAULT_POLICY;
  });
  return cached;
}

export type AuthProblem =
  | "email_required"
  | "invalid_email"
  | "username_required"
  | "invalid_username"
  | "password_required"
  | "password_too_short"
  | "password_too_long"
  | "password_needs_uppercase"
  | "password_needs_special"
  | "password_mismatch"
  | "identifier_required"
  // found by the availability check while typing (the server answers the same with 409)
  | "user_exists"
  | "username_taken";

export interface RegistrationForm {
  email: string;
  username: string;
  password: string;
  passwordConfirm: string;
}

export function registrationProblems(form: RegistrationForm, policy: AuthPolicy): AuthProblem[] {
  const problems: AuthProblem[] = [];
  const email = form.email.trim();
  if (!email) problems.push("email_required");
  else if (email.length > 254 || !new RegExp(policy.email_pattern).test(email)) problems.push("invalid_email");

  const username = form.username.trim().toLowerCase();
  if (!username) {
    if (policy.username_required) problems.push("username_required");
  } else if (!new RegExp(policy.username_pattern).test(username)) problems.push("invalid_username");

  if (!form.password) problems.push("password_required");
  else if (form.password.length < policy.password_min_length) problems.push("password_too_short");
  else if (new TextEncoder().encode(form.password).length > policy.password_max_length) problems.push("password_too_long");
  else {
    if (policy.password_require_uppercase && !hasUppercase(form.password)) problems.push("password_needs_uppercase");
    if (policy.password_require_special && !hasSpecial(form.password)) problems.push("password_needs_special");
  }

  if (form.password && form.password !== form.passwordConfirm) problems.push("password_mismatch");
  return problems;
}

export function loginProblems(identifier: string, password: string): AuthProblem[] {
  const problems: AuthProblem[] = [];
  if (!identifier.trim()) problems.push("identifier_required");
  if (!password) problems.push("password_required");
  return problems;
}
