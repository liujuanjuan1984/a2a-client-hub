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

export interface UserProfile {
  id: UUID;
  email: string;
  name: string;
  is_superuser: boolean;
  timezone: string;
}

export interface ApiErrorDetail {
  msg?: string;
  message?: string;
  loc?: (string | number)[];
  type?: string;
}

export interface ApiErrorResponse {
  detail?: string | ApiErrorDetail[];
  message?: string;
  error?: string;
}
