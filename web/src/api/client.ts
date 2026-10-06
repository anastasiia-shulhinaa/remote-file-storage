// REST client for the MiniDrive FastAPI backend. UI components call these
// functions instead of using fetch directly.
import { config } from "../config";
import type { HealthResponse } from "./types";

export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(`Cannot reach backend at ${config.apiBaseUrl}`);
  }

  if (!response.ok) {
    throw new ApiError(
      `Backend returned ${response.status} for ${init?.method ?? "GET"} ${path}`,
      response.status,
    );
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
};
