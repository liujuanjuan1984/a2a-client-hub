import type React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { ModelPickerModal } from "../ModelPickerModal";

import { listModelProviders, listModels } from "@/lib/api/a2aExtensions";

jest.mock("react-native/Libraries/Modal/Modal", () => {
  return {
    __esModule: true,
    default: ({
      children,
      visible = false,
    }: {
      children?: unknown;
      visible?: boolean;
    }) => (visible ? children : null),
    Modal: ({
      children,
      visible = false,
    }: {
      children?: unknown;
      visible?: boolean;
    }) => (visible ? children : null),
  };
});

jest.mock("@expo/vector-icons/Ionicons", () => () => null);

jest.mock("@/lib/api/a2aExtensions", () => {
  class MockA2AExtensionCallError extends Error {
    errorCode: string | null;
    upstreamError: Record<string, unknown> | null;

    constructor(
      message: string,
      options?: {
        errorCode?: string | null;
        upstreamError?: Record<string, unknown> | null;
      },
    ) {
      super(message);
      this.name = "A2AExtensionCallError";
      this.errorCode = options?.errorCode ?? null;
      this.upstreamError = options?.upstreamError ?? null;
    }
  }

  return {
    A2AExtensionCallError: MockA2AExtensionCallError,
    listModelProviders: jest.fn(),
    listModels: jest.fn(),
  };
});

const mockedListModelProviders = jest.mocked(listModelProviders);
const mockedListModels = jest.mocked(listModels);

type ModelPickerModalProps = React.ComponentProps<typeof ModelPickerModal>;

const baseProps: ModelPickerModalProps = {
  visible: true,
  onClose: jest.fn(),
  agentId: "agent-1",
  source: "shared" as const,
  providerDiscoveryStatus: "supported",
  sessionMetadata: {
    shared: { model: { providerID: "openai", modelID: "gpt-5" } },
    opencode: { directory: "/workspace" },
  },
  selectedModel: { providerID: "openai", modelID: "gpt-5" },
  onSelectModel: jest.fn(),
  onClearModelSelection: jest.fn(),
};

const renderModal = async (overrides?: Partial<ModelPickerModalProps>) => {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<ModelPickerModal {...baseProps} {...overrides} />);
  });
  await act(async () => {
    await Promise.resolve();
  });
  await act(async () => {
    await Promise.resolve();
  });
  act(() => {
    jest.runOnlyPendingTimers();
  });
  return tree;
};

describe("ModelPickerModal", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    mockedListModelProviders.mockReset();
    mockedListModels.mockReset();
  });

  afterEach(() => {
    act(() => {
      jest.runOnlyPendingTimers();
    });
    jest.useRealTimers();
  });

  it("forwards generic session metadata to model discovery APIs", async () => {
    mockedListModelProviders.mockResolvedValue({
      items: [
        {
          provider_id: "openai",
          name: "OpenAI",
          default_model_id: "gpt-5",
        },
      ],
      defaultByProvider: { openai: "gpt-5" },
      connected: ["openai"],
    });
    mockedListModels.mockResolvedValue({
      items: [
        {
          provider_id: "openai",
          model_id: "gpt-5",
          name: "GPT-5",
        },
      ],
      defaultByProvider: { openai: "gpt-5" },
      connected: ["openai"],
    });

    const tree = await renderModal();

    expect(mockedListModelProviders).toHaveBeenCalledWith({
      source: "shared",
      agentId: "agent-1",
      sessionMetadata: baseProps.sessionMetadata,
    });
    expect(mockedListModels).toHaveBeenCalledWith({
      source: "shared",
      agentId: "agent-1",
      providerId: "openai",
      sessionMetadata: baseProps.sessionMetadata,
    });

    act(() => {
      tree.unmount();
    });
  });

  it("renders provider-agnostic not-supported copy", async () => {
    const tree = await renderModal({
      source: "personal",
      providerDiscoveryStatus: "unsupported",
      selectedModel: null,
    });

    const textNodes = tree.root.findAll(
      (node) =>
        node.props?.children ===
        "This agent supports request-scoped model overrides but does not expose model discovery.",
    );

    expect(textNodes.length).toBeGreaterThan(0);
    expect(mockedListModelProviders).not.toHaveBeenCalled();
    expect(mockedListModels).not.toHaveBeenCalled();

    act(() => {
      tree.unmount();
    });
  });
});
