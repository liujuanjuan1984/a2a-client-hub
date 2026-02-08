import {
  buildHeaderObject,
  hasAuthorizationHeader,
  headersToEntries,
} from "@/lib/agentHeaders";

describe("agentHeaders helpers", () => {
  it("buildHeaderObject trims and removes empty entries", () => {
    const headers = buildHeaderObject([
      { key: " Authorization ", value: " Bearer token " },
      { key: "X-Empty", value: " " },
      { key: " ", value: "value" },
    ]);

    expect(headers).toEqual({ Authorization: "Bearer token" });
  });

  it("detects authorization header case-insensitively", () => {
    expect(hasAuthorizationHeader({ Authorization: "token" })).toBe(true);
    expect(hasAuthorizationHeader({ authorization: "token" })).toBe(true);
    expect(hasAuthorizationHeader({ "X-API-Key": "token" })).toBe(false);
  });

  it("converts header object to entries with ids", () => {
    const entries = headersToEntries({ Authorization: "token" });

    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      key: "Authorization",
      value: "token",
    });
    expect(entries[0].id).toEqual(expect.any(String));
    expect(entries[0].id.length).toBeGreaterThan(0);
  });
});
