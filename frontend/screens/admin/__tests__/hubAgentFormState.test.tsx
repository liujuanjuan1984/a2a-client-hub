import { act, renderHook } from "@testing-library/react-native";

import type { HubA2AAgentAdminResponse } from "@/lib/api/hubA2aAgentsAdmin";
import {
  buildHubAgentComparablePayload,
  buildHubAgentPayload,
  createHubAgentFormValuesFromRecord,
  useHubAgentFormState,
  type HubAgentFormValues,
} from "@/screens/admin/hubAgentFormState";

describe("hubAgentFormState", () => {
  it("builds comparable payload with normalized auth and tags", () => {
    const values: HubAgentFormValues = {
      name: " Agent Name ",
      cardUrl: " https://example.com/card.json ",
      enabled: true,
      availabilityPolicy: "allowlist",
      authType: "none",
      authHeader: " Authorization ",
      authScheme: " Bearer ",
      token: "  secret-token  ",
      tagsText: "alpha, beta, alpha",
      extraHeaders: [
        { id: "1", key: " X-Trace-Id ", value: " 123 " },
        { id: "2", key: "   ", value: "ignored" },
      ],
    };

    expect(buildHubAgentComparablePayload(values)).toEqual({
      name: "Agent Name",
      card_url: "https://example.com/card.json",
      enabled: true,
      availability_policy: "allowlist",
      auth_type: "none",
      auth_header: null,
      auth_scheme: null,
      tags: ["alpha", "beta"],
      extra_headers: { "X-Trace-Id": "123" },
    });
  });

  it("builds API payload and only includes token when non-empty", () => {
    const values: HubAgentFormValues = {
      name: " Agent Name ",
      cardUrl: " https://example.com/card.json ",
      enabled: false,
      availabilityPolicy: "public",
      authType: "bearer",
      authHeader: " Authorization ",
      authScheme: " Bearer ",
      token: "  ",
      tagsText: "prod, stable",
      extraHeaders: [{ id: "1", key: "X-Env", value: "prod" }],
    };

    expect(buildHubAgentPayload(values)).toEqual({
      name: "Agent Name",
      card_url: "https://example.com/card.json",
      availability_policy: "public",
      auth_type: "bearer",
      auth_header: "Authorization",
      auth_scheme: "Bearer",
      enabled: false,
      tags: ["prod", "stable"],
      extra_headers: { "X-Env": "prod" },
    });
  });

  it("hydrates from record and validates required fields", () => {
    const record: HubA2AAgentAdminResponse = {
      id: "agent-1",
      name: "Sample Agent",
      card_url: "https://example.com/agent.json",
      availability_policy: "public",
      auth_type: "none",
      auth_header: null,
      auth_scheme: null,
      enabled: true,
      tags: ["internal"],
      extra_headers: {},
      has_credential: false,
      token_last4: null,
      created_by_user_id: "user-1",
      updated_by_user_id: null,
      created_at: "2026-02-12T00:00:00.000Z",
      updated_at: "2026-02-12T00:00:00.000Z",
    };

    const { result } = renderHook(() => useHubAgentFormState());

    act(() => {
      result.current.setName(" ");
      result.current.setCardUrl("invalid-url");
    });
    act(() => {
      result.current.validate();
    });
    expect(result.current.errors.name).toBe("Name is required.");
    expect(result.current.errors.cardUrl).toBe(
      "Please enter a valid http(s) URL.",
    );

    act(() => {
      result.current.hydrateFromRecord(record);
    });
    const hydrated = result.current.values;
    const expected = createHubAgentFormValuesFromRecord(record);
    expect(hydrated).toMatchObject({
      ...expected,
      extraHeaders: [{ key: "", value: "" }],
    });
    expect(hydrated.extraHeaders).toHaveLength(1);
    expect(hydrated.extraHeaders[0]?.id).toBeTruthy();
    expect(result.current.errors).toEqual({});
  });
});
