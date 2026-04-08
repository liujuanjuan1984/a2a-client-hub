import { FlatList } from "react-native";
import { act, create, type ReactTestInstance } from "react-test-renderer";

import { SessionPickerModal } from "../SessionPickerModal";

import { useSessionsDirectoryQuery } from "@/hooks/useSessionsDirectoryQuery";
import { type SessionListItem } from "@/lib/api/sessions";
import { useChatStore } from "@/store/chat";

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

jest.mock("@/components/ui/Button", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => {
    const { Pressable, Text } = require("react-native");
    return (
      <Pressable onPress={onPress}>
        <Text>{label}</Text>
      </Pressable>
    );
  },
}));

jest.mock("@/hooks/useSessionsDirectoryQuery", () => ({
  useSessionsDirectoryQuery: jest.fn(),
}));

jest.mock("@/store/chat", () => ({
  useChatStore: jest.fn(),
}));

const mockedUseSessionsDirectoryQuery = jest.mocked(useSessionsDirectoryQuery);
const mockedUseChatStore = jest.mocked(useChatStore);

type SessionsDirectoryQueryResult = ReturnType<
  typeof useSessionsDirectoryQuery
>;
type ChatStoreSelector = NonNullable<Parameters<typeof useChatStore>[0]>;
type ChatStoreState = Parameters<ChatStoreSelector>[0];

const buildQueryResult = (
  overrides: Partial<SessionsDirectoryQueryResult> = {},
): SessionsDirectoryQueryResult => ({
  error: null,
  isError: false,
  pages: [],
  items: [],
  setItems: jest.fn(),
  nextPage: null,
  hasMore: false,
  loading: false,
  refreshing: false,
  loadingMore: false,
  reset: jest.fn(),
  loadFirstPage: jest.fn().mockResolvedValue(true),
  loadMore: jest.fn().mockResolvedValue(undefined),
  refresh: jest.fn().mockResolvedValue(undefined),
  ...overrides,
});

const buildSession = (
  overrides: Partial<SessionListItem> = {},
): SessionListItem => ({
  conversationId: "session-1",
  source: "manual",
  title: "Session One",
  created_at: "2026-03-19T15:00:00Z",
  last_active_at: "2026-03-19T15:00:00Z",
  ...overrides,
});

const findPressableByText = (
  root: ReactTestInstance,
  text: string,
): ReactTestInstance => {
  const textNode = root.findByProps({ children: text });
  let currentNode: ReactTestInstance | null = textNode;

  while (currentNode) {
    if (typeof currentNode.props.onPress === "function") {
      return currentNode;
    }
    currentNode = currentNode.parent;
  }

  throw new Error(`Could not find pressable for text: ${text}`);
};

const renderModal = async (
  overrides: Partial<React.ComponentProps<typeof SessionPickerModal>> = {},
) => {
  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(
      <SessionPickerModal
        visible
        onClose={jest.fn()}
        agentId="agent-1"
        onSelect={jest.fn()}
        {...overrides}
      />,
    );
  });
  return tree;
};

describe("SessionPickerModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUseChatStore.mockImplementation((selector) =>
      selector({
        generateConversationId: () => "generated-conversation-id",
      } as ChatStoreState),
    );
    mockedUseSessionsDirectoryQuery.mockReturnValue(
      buildQueryResult({
        items: [],
      }),
    );
  });

  it("creates a new session and closes the modal", async () => {
    const onClose = jest.fn();
    const onSelect = jest.fn();
    const tree = await renderModal({
      onClose,
      onSelect,
    });

    act(() => {
      findPressableByText(tree.root, "New Session").props.onPress();
    });

    expect(onSelect).toHaveBeenCalledWith("generated-conversation-id");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("selects an existing session and closes the modal", async () => {
    mockedUseSessionsDirectoryQuery.mockReturnValue(
      buildQueryResult({
        items: [buildSession()],
      }),
    );
    const onClose = jest.fn();
    const onSelect = jest.fn();
    const tree = await renderModal({
      onClose,
      onSelect,
      currentConversationId: "session-2",
    });

    act(() => {
      findPressableByText(tree.root, "Session One").props.onPress();
    });

    expect(onSelect).toHaveBeenCalledWith("session-1");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("loads more sessions when the list reaches the threshold", async () => {
    const loadMore = jest.fn().mockResolvedValue(undefined);
    mockedUseSessionsDirectoryQuery.mockReturnValue(
      buildQueryResult({
        items: [buildSession()],
        hasMore: true,
        loadMore,
      }),
    );
    const tree = await renderModal();

    await act(async () => {
      tree.root.findByType(FlatList).props.onEndReached();
      await Promise.resolve();
    });

    expect(loadMore).toHaveBeenCalledTimes(1);
  });
});
