import { buildAuthHeaders, type AgentAuthType } from "@/lib/agentAuth";
import {
  buildHeaderObject,
  hasAuthorizationHeader,
  type HeaderEntry,
} from "@/lib/agentHeaders";
import { type A2AAgentCreateRequest } from "@/lib/api/a2aAgents";

export type AgentUpsertInput = {
  name: string;
  cardUrl: string;
  authType: AgentAuthType;
  bearerToken: string;
  apiKeyHeader: string;
  apiKeyValue: string;
  basicUsername: string;
  basicPassword: string;
  extraHeaders: HeaderEntry[];
};

export const buildAgentUpsertPayload = (
  input: AgentUpsertInput,
): A2AAgentCreateRequest => {
  const customHeaders = buildHeaderObject(input.extraHeaders);
  const authHeaders = buildAuthHeaders({
    authType: input.authType,
    bearerToken: input.bearerToken,
    apiKeyHeader: input.apiKeyHeader,
    apiKeyValue: input.apiKeyValue,
    basicUsername: input.basicUsername,
    basicPassword: input.basicPassword,
  });
  const mergedHeaders = Object.assign({}, authHeaders, customHeaders);

  const payload: A2AAgentCreateRequest = {
    name: input.name.trim(),
    card_url: input.cardUrl.trim(),
    auth_type: "none",
    enabled: true,
    tags: [],
    extra_headers: {},
  };

  switch (input.authType) {
    case "bearer": {
      const token = input.bearerToken.trim();
      if (hasAuthorizationHeader(customHeaders)) {
        payload.auth_type = "none";
        payload.extra_headers = mergedHeaders;
      } else {
        payload.auth_type = "bearer";
        payload.auth_header = "Authorization";
        payload.auth_scheme = "Bearer";
        if (token) {
          payload.token = token;
        }
        payload.extra_headers = customHeaders;
      }
      break;
    }

    case "api_key":
    case "basic":
      payload.auth_type = "none";
      payload.extra_headers = mergedHeaders;
      break;

    case "none":
    default:
      payload.auth_type = "none";
      payload.extra_headers = customHeaders;
      break;
  }

  return payload;
};
