import { extractAgentCapabilitiesFromCard } from "@/lib/agentCapabilities";

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
});
