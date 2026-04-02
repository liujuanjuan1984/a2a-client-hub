import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react-native";

import { useShortcutsQuery } from "../useShortcutsQuery";

import { listShortcuts } from "@/lib/api/shortcuts";

jest.mock("@/lib/api/shortcuts", () => ({
  listShortcuts: jest.fn(),
  createShortcut: jest.fn(),
  updateShortcut: jest.fn(),
  deleteShortcut: jest.fn(),
}));

describe("useShortcutsQuery", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    jest.clearAllMocks();
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("should return sorted shortcuts for agent (agent specific first, system last)", async () => {
    (listShortcuts as jest.Mock).mockResolvedValue([
      {
        id: "custom-system-1",
        title: "Custom System",
        prompt: "System prompt",
        is_default: false,
        order: 10,
        agent_id: null,
        created_at: "2026-04-02T03:00:00Z",
      },
      {
        id: "agent-1-shortcut",
        title: "Agent 1 Shortcut",
        prompt: "Agent 1 prompt",
        is_default: false,
        order: 5,
        agent_id: "agent-1",
        created_at: "2026-04-02T04:00:00Z",
      },
      {
        id: "agent-2-shortcut",
        title: "Agent 2 Shortcut",
        prompt: "Agent 2 prompt",
        is_default: false,
        order: 6,
        agent_id: "agent-2",
        created_at: "2026-04-02T05:00:00Z",
      },
    ]);

    const { result } = renderHook(() => useShortcutsQuery(), { wrapper });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    const agent1Shortcuts = result.current.getShortcutsForAgent("agent-1");

    expect(agent1Shortcuts[0].id).toBe("agent-1-shortcut");
    expect(agent1Shortcuts[1].id).toBe("custom-system-1");
    expect(
      agent1Shortcuts.find((s) => s.id === "agent-2-shortcut"),
    ).toBeUndefined();
    expect(agent1Shortcuts.slice(2).every((s) => s.isDefault)).toBe(true);

    const globalShortcuts = result.current.getShortcutsForAgent(null);
    expect(globalShortcuts[0].id).toBe("custom-system-1");
    expect(globalShortcuts.slice(1).every((s) => s.isDefault)).toBe(true);
  });

  it("sorts custom shortcuts by newest first before appending defaults", async () => {
    (listShortcuts as jest.Mock).mockResolvedValue([
      {
        id: "system-b",
        title: "System B",
        prompt: "System prompt B",
        is_default: false,
        order: 11,
        agent_id: null,
        created_at: "2026-04-02T03:00:00Z",
      },
      {
        id: "agent-1-b",
        title: "Agent 1 B",
        prompt: "Agent 1 prompt B",
        is_default: false,
        order: 8,
        agent_id: "agent-1",
        created_at: "2026-04-02T04:00:00Z",
      },
      {
        id: "agent-1-a",
        title: "Agent 1 A",
        prompt: "Agent 1 prompt A",
        is_default: false,
        order: 2,
        agent_id: "agent-1",
        created_at: "2026-04-02T02:00:00Z",
      },
      {
        id: "system-a",
        title: "System A",
        prompt: "System prompt A",
        is_default: false,
        order: 1,
        agent_id: null,
        created_at: "2026-04-02T05:00:00Z",
      },
    ]);

    const { result } = renderHook(() => useShortcutsQuery(), { wrapper });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    const agent1Shortcuts = result.current.getShortcutsForAgent("agent-1");

    expect(agent1Shortcuts.map((shortcut) => shortcut.id)).toEqual([
      "agent-1-b",
      "agent-1-a",
      "system-a",
      "system-b",
      "11111111-1111-1111-1111-111111111111",
      "22222222-2222-2222-2222-222222222222",
      "33333333-3333-3333-3333-333333333333",
      "44444444-4444-4444-4444-444444444444",
      "55555555-5555-5555-5555-555555555555",
    ]);
  });
});
