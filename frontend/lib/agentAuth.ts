import { encode as btoa } from "base-64";

export type AgentAuthType = "none" | "bearer" | "api_key" | "basic";

export type AgentAuthFields = {
  authType: AgentAuthType;
  bearerToken: string;
  apiKeyHeader: string;
  apiKeyValue: string;
  basicUsername: string;
  basicPassword: string;
};

const toBase64 = (value: string) => {
  try {
    return btoa(value);
  } catch (error) {
    throw new Error(
      `Base64 encoding failed: ${error instanceof Error ? error.message : "Unknown error"}`,
    );
  }
};

export const buildAuthHeaders = (auth: AgentAuthFields) => {
  const headers: Record<string, string> = {};

  switch (auth.authType) {
    case "bearer": {
      const token = auth.bearerToken.trim();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      break;
    }

    case "api_key": {
      const headerName = auth.apiKeyHeader.trim();
      const value = auth.apiKeyValue.trim();
      if (headerName && value) {
        headers[headerName] = value;
      }
      break;
    }

    case "basic": {
      const username = auth.basicUsername.trim();
      const password = auth.basicPassword.trim();
      if (username && password) {
        const credentials = toBase64(`${username}:${password}`);
        headers["Authorization"] = `Basic ${credentials}`;
      }
      break;
    }

    case "none":
    default:
      break;
  }

  return headers;
};
