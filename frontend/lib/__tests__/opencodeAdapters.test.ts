import {
  getOpencodeMessageRole,
  getOpencodeMessageText,
  getOpencodeSessionId,
  getOpencodeSessionTitle,
} from "@/lib/opencodeAdapters";

describe("opencodeAdapters", () => {
  it("extracts session id/title from common fields", () => {
    expect(getOpencodeSessionId({ id: "s-1" })).toBe("s-1");
    expect(getOpencodeSessionTitle({ title: "Hello" })).toBe("Hello");
    expect(getOpencodeSessionTitle({ id: "s-2" })).toBe("s-2");
  });

  it("extracts message role/text from common fields", () => {
    expect(getOpencodeMessageRole({ role: "assistant" })).toBe("assistant");
    expect(getOpencodeMessageText({ text: "hi" })).toBe("hi");
    expect(getOpencodeMessageText({ content: "hello" })).toBe("hello");
  });

  it("falls back safely for unknown shapes", () => {
    expect(getOpencodeSessionTitle(null)).toBe("Session");
    expect(getOpencodeMessageRole(null)).toBe("message");
    expect(getOpencodeMessageText({})).toContain("{");
  });
});
