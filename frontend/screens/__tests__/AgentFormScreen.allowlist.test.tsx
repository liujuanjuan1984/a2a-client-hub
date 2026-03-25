import { fireEvent, render, waitFor } from "@testing-library/react-native";

import { AgentFormScreen } from "@/screens/AgentFormScreen";
import { useSessionStore } from "@/store/session";

const mockRouter = {
  back: jest.fn(),
  replace: jest.fn(),
  canGoBack: jest.fn(() => true),
};
const mockAgentsCatalog = [] as Record<string, unknown>[];
const mockCreateAgent = jest.fn();
const mockUpdateAgent = jest.fn();
const mockDeleteAgent = jest.fn();
const mockValidateAgent = jest.fn();
const mockAllowNextNavigation = jest.fn();
const mockBackOrHome = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();
const mockCreateProxyAllowlistEntry = jest.fn();
const mockConfirmAction = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
}));

jest.mock("@/hooks/useAgentsCatalogQuery", () => ({
  useAgentsCatalogQuery: () => ({
    data: mockAgentsCatalog,
    isFetched: true,
  }),
  useCreateAgentMutation: () => ({
    mutateAsync: mockCreateAgent,
  }),
  useUpdateAgentMutation: () => ({
    mutateAsync: mockUpdateAgent,
  }),
  useDeleteAgentMutation: () => ({
    mutateAsync: mockDeleteAgent,
  }),
  useValidateAgentMutation: () => ({
    mutateAsync: mockValidateAgent,
    isPending: false,
  }),
}));

jest.mock("@/hooks/usePreventRemoveWhenDirty", () => ({
  usePreventRemoveWhenDirty: () => ({
    allowNextNavigation: mockAllowNextNavigation,
  }),
}));

jest.mock("@/lib/api/adminProxyAllowlist", () => ({
  createProxyAllowlistEntry: (...args: unknown[]) =>
    mockCreateProxyAllowlistEntry(...args),
}));

jest.mock("@/lib/confirm", () => ({
  confirmAction: (...args: unknown[]) => mockConfirmAction(...args),
}));

jest.mock("@/lib/navigation", () => ({
  backOrHome: (...args: unknown[]) => mockBackOrHome(...args),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

jest.mock("@/lib/focus", () => ({
  blurActiveElement: jest.fn(),
}));

jest.mock("@/components/layout/ScreenScrollView", () => ({
  ScreenScrollView: ({ children }: { children: unknown }) => children,
}));

jest.mock("@/components/ui/PageHeader", () => ({
  PageHeader: () => null,
}));

jest.mock("@/components/ui/BackButton", () => ({
  BackButton: ({ onPress }: { onPress: () => void }) => {
    const { Pressable, Text } = require("react-native");
    return (
      <Pressable accessibilityRole="button" onPress={onPress}>
        <Text>Back</Text>
      </Pressable>
    );
  },
}));

jest.mock("@/components/ui/IconButton", () => ({
  IconButton: ({ onPress }: { onPress: () => void }) => {
    const { Pressable, Text } = require("react-native");
    return (
      <Pressable accessibilityRole="button" onPress={onPress}>
        <Text>Icon</Text>
      </Pressable>
    );
  },
}));

jest.mock("@/components/ui/Button", () => {
  const React = require("react");
  const { Pressable, Text } = require("react-native");
  return {
    Button: ({
      label,
      onPress,
      disabled,
    }: {
      label: string;
      onPress: () => void;
      disabled?: boolean;
    }) => (
      <Pressable
        accessibilityRole="button"
        onPress={onPress}
        disabled={disabled}
      >
        <Text>{label}</Text>
      </Pressable>
    ),
  };
});

jest.mock("@/components/ui/Input", () => {
  const React = require("react");
  const { TextInput } = require("react-native");
  return {
    Input: ({
      placeholder,
      value,
      onChangeText,
    }: {
      placeholder?: string;
      value?: string;
      onChangeText?: (value: string) => void;
    }) => (
      <TextInput
        placeholder={placeholder}
        value={value}
        onChangeText={onChangeText}
      />
    ),
  };
});

jest.mock("@/components/ui/KeyValueInputRow", () => ({
  KeyValueInputRow: () => null,
}));

describe("AgentFormScreen auto allowlist create flow", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockAgentsCatalog.length = 0;
    useSessionStore.setState({
      user: {
        id: "admin-1",
        email: "admin@example.com",
        name: "Admin",
        is_superuser: true,
        timezone: "UTC",
      },
    });
  });

  it("allows admin users to auto-add host to allowlist and continue create", async () => {
    mockCreateAgent
      .mockRejectedValueOnce(
        Object.assign(new Error("Card URL host is not allowed"), {
          status: 403,
          errorCode: "card_url_host_not_allowed",
        }),
      )
      .mockResolvedValueOnce({ id: "agent-1" });
    mockConfirmAction.mockResolvedValue(true);
    mockCreateProxyAllowlistEntry.mockResolvedValue({ id: "allow-1" });

    const screen = render(<AgentFormScreen />);

    fireEvent.changeText(
      screen.getByPlaceholderText("Agent name"),
      "Admin Agent",
    );
    fireEvent.changeText(
      screen.getByPlaceholderText(
        "https://agent.example.com/.well-known/agent.json",
      ),
      "https://blocked.example.com:8443/agent.json",
    );
    fireEvent.press(screen.getByText("Save"));

    await waitFor(() => {
      expect(mockConfirmAction).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Host not allowlisted",
          confirmLabel: "Add and Continue",
        }),
      );
    });
    await waitFor(() => {
      expect(mockCreateProxyAllowlistEntry).toHaveBeenCalledWith({
        host_pattern: "blocked.example.com:8443",
      });
    });
    await waitFor(() => {
      expect(mockCreateAgent).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith(
        "Success",
        "Agent saved successfully.",
      );
    });
  });

  it("allows admin users to auto-add host to allowlist and continue update", async () => {
    mockAgentsCatalog.push({
      id: "agent-1",
      name: "Existing Agent",
      cardUrl: "https://existing.example.com/agent.json",
      authType: "none",
      bearerToken: "",
      apiKeyHeader: "X-API-Key", // pragma: allowlist secret
      apiKeyValue: "",
      basicUsername: "",
      basicPassword: "",
      extraHeaders: [],
      source: "user",
    });
    mockUpdateAgent
      .mockRejectedValueOnce(
        Object.assign(new Error("Card URL host is not allowed"), {
          status: 403,
          errorCode: "card_url_host_not_allowed",
        }),
      )
      .mockResolvedValueOnce({ id: "agent-1" });
    mockConfirmAction.mockResolvedValue(true);
    mockCreateProxyAllowlistEntry.mockResolvedValue({ id: "allow-2" });

    const screen = render(<AgentFormScreen agentId="agent-1" />);

    fireEvent.changeText(
      screen.getByPlaceholderText(
        "https://agent.example.com/.well-known/agent.json",
      ),
      "https://edited.example.com:8443/agent.json",
    );
    fireEvent.press(screen.getByText("Save"));

    await waitFor(() => {
      expect(mockConfirmAction).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Host not allowlisted",
          confirmLabel: "Add and Continue",
          cancelLabel: "Keep Editing",
        }),
      );
    });
    await waitFor(() => {
      expect(mockCreateProxyAllowlistEntry).toHaveBeenCalledWith({
        host_pattern: "edited.example.com:8443",
      });
    });
    await waitFor(() => {
      expect(mockUpdateAgent).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith(
        "Success",
        "Agent saved successfully.",
      );
    });
    expect(mockAllowNextNavigation).toHaveBeenCalledTimes(1);
    expect(mockBackOrHome).toHaveBeenCalled();
  });
});
