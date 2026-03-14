import {
  AGENT_CAPABILITY_TTL_MS,
  extractAgentCapabilitiesFromCard,
  getAgentSessionBindingWriteMode,
} from "@/lib/agentCapabilities";

describe("agent capability helpers", () => {
  it("parses canonical session-binding extension as declared contract", () => {
    expect(
      extractAgentCapabilitiesFromCard({
        capabilities: {
          extensions: [
            {
              uri: "urn:a2a:session-binding/v1",
              params: {
                metadata_field: "metadata.shared.session.id",
              },
            },
          ],
        },
      }),
    ).toEqual({
      sessionBinding: {
        declared: true,
        mode: "declared_contract",
        uri: "urn:a2a:session-binding/v1",
        metadataField: "metadata.shared.session.id",
      },
    });
  });

  it("falls back to compatibility mode when extension is missing", () => {
    expect(
      extractAgentCapabilitiesFromCard({ capabilities: { extensions: [] } }),
    ).toEqual({
      sessionBinding: {
        declared: false,
        mode: "compat_fallback",
        uri: null,
        metadataField: null,
      },
    });
  });

  it("reads session binding write mode from cached agent config", () => {
    expect(
      getAgentSessionBindingWriteMode(
        {
          status: "success",
          lastCheckedAt: "2026-03-14T00:00:00.000Z",
          capabilities: {
            sessionBinding: {
              declared: true,
              mode: "declared_contract",
            },
          },
        },
        Date.parse("2026-03-14T01:00:00.000Z"),
      ),
    ).toBe("declared_contract");
    expect(getAgentSessionBindingWriteMode(null)).toBe("unknown");
  });

  it("treats stale validation state as unknown", () => {
    expect(
      getAgentSessionBindingWriteMode(
        {
          status: "success",
          lastCheckedAt: "2026-03-14T00:00:00.000Z",
          capabilities: {
            sessionBinding: {
              declared: true,
              mode: "declared_contract",
            },
          },
        },
        Date.parse("2026-03-14T00:00:00.000Z") + AGENT_CAPABILITY_TTL_MS + 1,
      ),
    ).toBe("unknown");
  });

  it("treats failed or unchecked validation state as unknown", () => {
    expect(
      getAgentSessionBindingWriteMode({
        status: "error",
        lastCheckedAt: "2026-03-14T00:00:00.000Z",
        capabilities: {
          sessionBinding: {
            declared: true,
            mode: "declared_contract",
          },
        },
      }),
    ).toBe("unknown");
    expect(
      getAgentSessionBindingWriteMode({
        status: "success",
        capabilities: {
          sessionBinding: {
            declared: true,
            mode: "declared_contract",
          },
        },
      }),
    ).toBe("unknown");
  });
});
