import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { ShortcutManagerModal } from "../ShortcutManagerModal";

import { toast } from "@/lib/toast";

type ShortcutItem = {
  id: string;
  title: string;
  prompt: string;
  isDefault: boolean;
  order: number;
  agentId?: string | null;
};

const mockCreateShortcut = jest.fn(async (_payload: unknown) => undefined);
const mockUpdateShortcut = jest.fn(async (_payload: unknown) => undefined);
const mockDeleteShortcut = jest.fn(async (_payload: unknown) => undefined);

const mockShortcutState: {
  shortcuts: ShortcutItem[];
  getShortcutsForAgent: jest.Mock;
} = {
  shortcuts: [],
  getShortcutsForAgent: jest
    .fn()
    .mockImplementation(() => mockShortcutState.shortcuts),
};

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

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

jest.mock("@/hooks/useShortcutsQuery", () => ({
  useShortcutsQuery: () => mockShortcutState,
  useCreateShortcutMutation: () => ({
    mutateAsync: (payload: unknown) => mockCreateShortcut(payload),
  }),
  useUpdateShortcutMutation: () => ({
    mutateAsync: (payload: unknown) => mockUpdateShortcut(payload),
  }),
  useDeleteShortcutMutation: () => ({
    mutateAsync: (payload: unknown) => mockDeleteShortcut(payload),
  }),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const renderModal = () => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <ShortcutManagerModal
        visible
        onClose={jest.fn()}
        onUseShortcut={jest.fn()}
        initialPrompt=""
        agentId="agent-1"
      />,
    );
  });
  return tree;
};

describe("ShortcutManagerModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockShortcutState.shortcuts = [];
  });

  it("creates shortcut with title and prompt", async () => {
    const tree = renderModal();
    const root = tree.root;

    act(() => {
      root.findByProps({ label: "New Shortcut" }).props.onPress();
    });

    act(() => {
      root
        .findByProps({ placeholder: "Shortcut title" })
        .props.onChangeText("Daily Summary");
      root
        .findByProps({ placeholder: "Prompt" })
        .props.onChangeText("Summarize today in 3 points.");
    });

    await act(async () => {
      await root.findByProps({ label: "Save" }).props.onPress();
    });

    expect(mockCreateShortcut).toHaveBeenCalledWith({
      title: "Daily Summary",
      prompt: "Summarize today in 3 points.",
      agentId: null,
    });
    expect(toast.success).toHaveBeenCalledWith(
      "Shortcut saved",
      '"Daily Summary" is now available.',
    );
    act(() => tree.unmount());
  });

  it("edits existing shortcut and updates title/prompt", async () => {
    mockShortcutState.shortcuts = [
      {
        id: "shortcut-1",
        title: "Old title",
        prompt: "Old prompt",
        isDefault: false,
        order: 0,
        agentId: "agent-1",
      },
    ];

    const tree = renderModal();
    const root = tree.root;

    await act(async () => {
      await root
        .findByProps({ accessibilityLabel: "Edit shortcut Old title" })
        .props.onPress();
    });

    act(() => {
      root
        .findByProps({ placeholder: "Shortcut title" })
        .props.onChangeText("Updated title");
      root
        .findByProps({ placeholder: "Prompt" })
        .props.onChangeText("Updated prompt");
    });

    await act(async () => {
      await root.findByProps({ label: "Update" }).props.onPress();
    });

    expect(mockUpdateShortcut).toHaveBeenCalledWith({
      shortcutId: "shortcut-1",
      title: "Updated title",
      prompt: "Updated prompt",
      agentId: "agent-1",
      clearAgent: false,
    });
    expect(toast.success).toHaveBeenCalledWith(
      "Shortcut updated",
      '"Updated title" has been updated.',
    );
    act(() => tree.unmount());
  });

  it("does not show edit action for default shortcut", () => {
    mockShortcutState.shortcuts = [
      {
        id: "shortcut-default",
        title: "Default title",
        prompt: "Default prompt",
        isDefault: true,
        order: 0,
      },
    ];

    const tree = renderModal();
    const root = tree.root;
    const editActions = root.findAll((node) => {
      return (
        typeof node.props.accessibilityLabel === "string" &&
        node.props.accessibilityLabel.startsWith("Edit shortcut")
      );
    });

    expect(editActions).toHaveLength(0);
    act(() => tree.unmount());
  });
});
