import { parseComposerInput } from "@/lib/sessionCommand";

describe("parseComposerInput", () => {
  it("keeps normal chat input as message text", () => {
    expect(parseComposerInput("hello world")).toEqual({
      kind: "message",
      text: "hello world",
    });
  });

  it("parses a single-line slash command", () => {
    expect(parseComposerInput("/review --quick")).toEqual({
      kind: "command",
      command: "/review",
      arguments: "--quick",
      prompt: "",
    });
  });

  it("parses a no-argument slash command", () => {
    expect(parseComposerInput("/status")).toEqual({
      kind: "command",
      command: "/status",
      arguments: "",
      prompt: "",
    });
  });

  it("parses multiline prompt content into parts text", () => {
    expect(
      parseComposerInput("/review --quick\nFocus on tests\nBe concise"),
    ).toEqual({
      kind: "command",
      command: "/review",
      arguments: "--quick",
      prompt: "Focus on tests\nBe concise",
    });
  });

  it("supports // escape for literal slash messages", () => {
    expect(parseComposerInput("//status")).toEqual({
      kind: "message",
      text: "/status",
    });
  });
});
