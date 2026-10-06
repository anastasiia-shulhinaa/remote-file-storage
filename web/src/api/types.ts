// Typed REST contracts shared by the Web client. Mirror the backend Pydantic DTOs.

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
}
