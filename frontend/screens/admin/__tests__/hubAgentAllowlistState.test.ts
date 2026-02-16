import { type HubA2AAllowlistEntryResponse } from "@/lib/api/hubA2aAgentsAdmin";
import {
  buildAllowlistReplaceEntries,
  buildAllowlistDraftFromEntries,
  buildNewAllowlistDraftEntry,
  deriveAllowlistChanges,
  hasAllowlistEmail,
} from "@/screens/admin/hubAgentAllowlistState";

const existingEntry = (
  partial: Partial<HubA2AAllowlistEntryResponse>,
): HubA2AAllowlistEntryResponse => ({
  id: "entry-1",
  agent_id: "agent-1",
  user_id: "user-1",
  user_email: "user-1@example.com",
  user_name: "User 1",
  created_by_user_id: "admin-1",
  created_at: "2026-02-16T00:00:00.000Z",
  ...partial,
});

describe("hubAgentAllowlistState", () => {
  it("builds draft rows from existing allowlist entries", () => {
    const rows = buildAllowlistDraftFromEntries([
      existingEntry({ id: "entry-a", user_email: "a@example.com" }),
    ]);
    expect(rows).toEqual([
      {
        id: "existing:entry-a",
        existingUserId: "user-1",
        email: "a@example.com",
        userLabel: "a@example.com",
        userId: "user-1",
      },
    ]);
  });

  it("detects duplicated email regardless of case", () => {
    const rows = [buildNewAllowlistDraftEntry("Alice@example.com", "1")];
    expect(hasAllowlistEmail(rows, "alice@EXAMPLE.com")).toBe(true);
  });

  it("derives add/remove changes between base and draft", () => {
    const base = [
      existingEntry({ id: "entry-a", user_email: "a@example.com" }),
      existingEntry({
        id: "entry-b",
        user_id: "user-2",
        user_email: "b@example.com",
      }),
    ];
    const draft = [
      ...buildAllowlistDraftFromEntries([base[0]]),
      buildNewAllowlistDraftEntry("new@example.com", "new-1"),
    ];

    expect(deriveAllowlistChanges(base, draft)).toEqual({
      addEmails: ["new@example.com"],
      removeUserIds: ["user-2"],
    });
  });

  it("builds replace payload entries from mixed draft rows", () => {
    const draft = [
      ...buildAllowlistDraftFromEntries([
        existingEntry({
          id: "entry-a",
          user_id: "user-a",
          user_email: "a@example.com",
        }),
      ]),
      buildNewAllowlistDraftEntry("new@example.com", "new-1"),
    ];
    expect(buildAllowlistReplaceEntries(draft)).toEqual([
      { user_id: "user-a" },
      { email: "new@example.com" },
    ]);
  });
});
