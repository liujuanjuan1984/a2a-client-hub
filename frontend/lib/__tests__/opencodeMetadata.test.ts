import {
  getOpencodeDirectory,
  pickOpencodeDirectoryMetadata,
  withOpencodeDirectory,
} from "@/lib/opencodeMetadata";

describe("opencode metadata helpers", () => {
  it("reads a normalized directory from provider-private metadata", () => {
    expect(
      getOpencodeDirectory({
        opencode: {
          directory: "  /workspace/demo  ",
        },
      }),
    ).toBe("/workspace/demo");
  });

  it("writes a directory while preserving unrelated metadata", () => {
    expect(
      withOpencodeDirectory(
        {
          locale: "en-CA",
          shared: {
            model: {
              providerID: "openai",
              modelID: "gpt-5",
            },
          },
        },
        "/workspace/demo",
      ),
    ).toEqual({
      locale: "en-CA",
      shared: {
        model: {
          providerID: "openai",
          modelID: "gpt-5",
        },
      },
      opencode: {
        directory: "/workspace/demo",
      },
    });
  });

  it("removes the directory key and empties the provider section when cleared", () => {
    expect(
      withOpencodeDirectory(
        {
          opencode: {
            directory: "/workspace/demo",
          },
        },
        null,
      ),
    ).toEqual({});
  });

  it("picks only the directory metadata for extension callbacks", () => {
    expect(
      pickOpencodeDirectoryMetadata({
        shared: {
          model: {
            providerID: "openai",
            modelID: "gpt-5",
          },
        },
        opencode: {
          directory: "/workspace/demo",
        },
      }),
    ).toEqual({
      opencode: {
        directory: "/workspace/demo",
      },
    });
  });
});
