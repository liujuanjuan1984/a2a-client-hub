import {
  AGENT_ERROR_MESSAGES,
  mergeTransientAgentState,
  patchAgentInCatalog,
  removeAgentFromCatalog,
  shouldClearActiveAgent,
  toValidationErrorMessage,
  upsertAgentInCatalog,
} from "@/lib/agentCatalogCache";
import { createMockAgentConfig } from "@/test-utils/agentFixtures";

describe("agentCatalogCache", () => {
  it("merges transient status fields from previous catalog", () => {
    const previous = [
      createMockAgentConfig({
        id: "agent-1",
        status: "error",
        lastCheckedAt: "2026-02-12T01:02:03.000Z",
        lastError: "timeout",
      }),
    ];

    const next = [
      createMockAgentConfig({ id: "agent-1", name: "Agent One Updated" }),
    ];

    expect(mergeTransientAgentState(next, previous)).toEqual([
      createMockAgentConfig({
        id: "agent-1",
        name: "Agent One Updated",
        status: "error",
        lastCheckedAt: "2026-02-12T01:02:03.000Z",
        lastError: "timeout",
      }),
    ]);
  });

  it("drops validation state when the agent card identity changes", () => {
    const previous = [
      createMockAgentConfig({
        id: "agent-1",
        status: "success",
        lastCheckedAt: "2026-02-12T01:02:03.000Z",
      }),
    ];

    const next = [
      createMockAgentConfig({
        id: "agent-1",
        cardUrl: "https://example.com/agent-1-updated.json",
      }),
    ];

    expect(mergeTransientAgentState(next, previous)).toEqual(next);
  });

  it("updates a specific agent in catalog", () => {
    const catalog = [
      createMockAgentConfig({ id: "agent-1" }),
      createMockAgentConfig({ id: "agent-2" }),
    ];

    const updated = patchAgentInCatalog(catalog, "agent-2", (agent) => ({
      ...agent,
      status: "success",
    }));

    expect(updated?.find((item) => item.id === "agent-2")?.status).toBe(
      "success",
    );
  });

  it("upserts agent and preserves transient status from previous record", () => {
    const catalog = [
      createMockAgentConfig({
        id: "agent-1",
        status: "success",
        lastError: "old",
      }),
      createMockAgentConfig({ id: "agent-2" }),
    ];

    const updated = upsertAgentInCatalog(
      catalog,
      createMockAgentConfig({ id: "agent-1", name: "Renamed", status: "idle" }),
      "agent-1",
    );

    expect(updated[0]).toMatchObject({
      id: "agent-1",
      name: "Renamed",
      status: "success",
      lastError: "old",
    });
    expect(updated).toHaveLength(2);
  });

  it("drops transient validation state on upsert when card identity changes", () => {
    const catalog = [
      createMockAgentConfig({
        id: "agent-1",
        status: "success",
        lastCheckedAt: "2026-02-12T01:02:03.000Z",
      }),
    ];

    const updated = upsertAgentInCatalog(
      catalog,
      createMockAgentConfig({
        id: "agent-1",
        cardUrl: "https://example.com/agent-1-updated.json",
      }),
      "agent-1",
    );

    expect(updated[0]).toMatchObject({
      id: "agent-1",
      cardUrl: "https://example.com/agent-1-updated.json",
      status: "idle",
      lastCheckedAt: undefined,
    });
  });

  it("removes agent from catalog", () => {
    const catalog = [
      createMockAgentConfig({ id: "agent-1" }),
      createMockAgentConfig({ id: "agent-2" }),
    ];

    expect(removeAgentFromCatalog(catalog, "agent-1")).toEqual([
      createMockAgentConfig({ id: "agent-2" }),
    ]);
  });

  it("decides whether active agent should be cleared", () => {
    const catalog = [createMockAgentConfig({ id: "agent-1" })];

    expect(shouldClearActiveAgent("agent-1", catalog)).toBe(false);
    expect(shouldClearActiveAgent("missing", catalog)).toBe(true);
    expect(shouldClearActiveAgent(null, catalog)).toBe(false);
  });

  it("builds validation error message with fallback", () => {
    expect(
      toValidationErrorMessage({
        validation_errors: ["bad config"],
      }),
    ).toBe("bad config");

    expect(
      toValidationErrorMessage({
        success: false,
        message: { detail: "bad" },
      } as any),
    ).toBe('{"detail":"bad"}');

    expect(toValidationErrorMessage({})).toBe(
      AGENT_ERROR_MESSAGES.connectionFailed,
    );
  });

  it("does not treat warning-only validation payloads as error details", () => {
    expect(
      toValidationErrorMessage({
        validation_warnings: ["empty skills"],
        message: "Agent card validated with warnings",
      }),
    ).toBe("Agent card validated with warnings");
  });
});
