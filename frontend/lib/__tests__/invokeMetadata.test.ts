import {
  getInvokeMetadataBindings,
  withInvokeMetadataBindings,
} from "@/lib/invokeMetadata";

describe("invoke metadata helpers", () => {
  it("reads invoke metadata bindings from shared metadata", () => {
    expect(
      getInvokeMetadataBindings({
        shared: {
          invoke: {
            bindings: {
              project_id: "proj-1",
              channel_id: "chan-1",
            },
          },
        },
      }),
    ).toEqual({
      project_id: "proj-1",
      channel_id: "chan-1",
    });
  });

  it("writes invoke metadata bindings into shared metadata", () => {
    expect(
      withInvokeMetadataBindings(
        {
          shared: {
            model: {
              providerID: "openai",
              modelID: "gpt-5",
            },
          },
        },
        {
          project_id: "proj-1",
          channel_id: "chan-1",
        },
      ),
    ).toEqual({
      shared: {
        model: {
          providerID: "openai",
          modelID: "gpt-5",
        },
        invoke: {
          bindings: {
            project_id: "proj-1",
            channel_id: "chan-1",
          },
        },
      },
    });
  });

  it("removes invoke metadata section when bindings are cleared", () => {
    expect(
      withInvokeMetadataBindings(
        {
          shared: {
            invoke: {
              bindings: {
                project_id: "proj-1",
              },
            },
          },
        },
        {},
      ),
    ).toEqual({});
  });
});
