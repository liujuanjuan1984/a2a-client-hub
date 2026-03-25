export type UUID = string;

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: UserProfile;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  name: string;
  timezone?: string;
  invite_code?: string;
}

export interface UserProfile {
  id: UUID;
  email: string;
  name: string;
  is_superuser: boolean;
  timezone: string;
}

export interface ApiFieldErrorDetail {
  msg?: string;
  message?: string;
  loc?: (string | number)[];
  type?: string;
}

export interface ApiStructuredErrorDetail {
  message?: string;
  error_code?: string | null;
  source?: string | null;
  jsonrpc_code?: number | null;
  missing_params?: { name: string; required: boolean }[] | null;
  upstream_error?: Record<string, unknown> | null;
  errors?: ApiFieldErrorDetail[];
  meta?: Record<string, unknown> | null;
}

export interface ApiErrorResponse {
  detail?: string | ApiFieldErrorDetail[] | ApiStructuredErrorDetail;
  message?: string;
  error?: string;
}
