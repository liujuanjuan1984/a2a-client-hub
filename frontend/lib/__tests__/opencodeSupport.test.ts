import {
  OPENCODE_SESSION_QUERY_URI,
  supportsOpencodeSessionQuery,
} from "@/lib/opencodeSupport";

describe("supportsOpencodeSessionQuery", () => {
  it("returns false for null/invalid cards", () => {
    expect(supportsOpencodeSessionQuery(null)).toBe(false);
    expect(supportsOpencodeSessionQuery(undefined)).toBe(false);
    expect(supportsOpencodeSessionQuery("not-an-object")).toBe(false);
    expect(supportsOpencodeSessionQuery({})).toBe(false);
  });

  it("returns true when capabilities.extensions contains the URI", () => {
    const card = {
      capabilities: {
        extensions: [{ uri: OPENCODE_SESSION_QUERY_URI }],
      },
    };
    expect(supportsOpencodeSessionQuery(card)).toBe(true);
  });

  it("returns false when capabilities.extensions is missing or does not contain the URI", () => {
    const card = {
      capabilities: {
        extensions: [{ uri: "urn:other" }],
      },
    };
    expect(supportsOpencodeSessionQuery(card)).toBe(false);
  });
});
