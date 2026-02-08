import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";

describe("mapSessionMessagesToChatMessages", () => {
  it("maps roles, fills ids, and sorts by created_at", () => {
    const result = mapSessionMessagesToChatMessages(
      [
        {
          role: "assistant",
          content: "A",
          created_at: "2025-01-02T00:00:00.000Z",
        },
        {
          id: "m-2",
          role: "user",
          content: "U",
          created_at: "2025-01-01T00:00:00.000Z",
        },
        {
          role: "unknown",
          content: "S",
          created_at: "2025-01-03T00:00:00.000Z",
        },
      ],
      "sess-remote",
    );

    expect(result.map((m) => m.role)).toEqual(["user", "agent", "system"]);
    expect(result.map((m) => m.content)).toEqual(["U", "A", "S"]);
    expect(result[0].id).toBe("m-2");
    expect(result[1].id).toBe("sess-remote-2025-01-02T00:00:00.000Z-0");
    expect(result[2].id).toBe("sess-remote-2025-01-03T00:00:00.000Z-2");
  });
});
