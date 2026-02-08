import { buildAuthHeaders, type AgentAuthFields } from "@/lib/agentAuth";

describe("buildAuthHeaders", () => {
  const baseFields: AgentAuthFields = {
    authType: "none",
    bearerToken: "",
    apiKeyHeader: "",
    apiKeyValue: "",
    basicUsername: "",
    basicPassword: "",
  };

  it("returns empty headers for none", () => {
    expect(buildAuthHeaders(baseFields)).toEqual({});
  });

  it("adds bearer token header when provided", () => {
    const headers = buildAuthHeaders({
      ...baseFields,
      authType: "bearer",
      bearerToken: "  token-123  ",
    });
    expect(headers).toEqual({ Authorization: "Bearer token-123" });
  });

  it("adds api key header when provided", () => {
    const headers = buildAuthHeaders({
      ...baseFields,
      authType: "api_key",
      apiKeyHeader: " X-API-Key ",
      apiKeyValue: " secret ",
    });
    expect(headers).toEqual({ "X-API-Key": "secret" });
  });

  it("adds basic auth header when username and password present", () => {
    const headers = buildAuthHeaders({
      ...baseFields,
      authType: "basic",
      basicUsername: "user",
      basicPassword: "pass",
    });
    expect(headers).toEqual({ Authorization: "Basic dXNlcjpwYXNz" });
  });
});
