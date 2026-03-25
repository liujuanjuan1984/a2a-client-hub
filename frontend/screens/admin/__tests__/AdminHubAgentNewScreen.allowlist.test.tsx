import { fireEvent, render, waitFor } from "@testing-library/react-native";

import { AdminHubAgentNewScreen } from "@/screens/admin/AdminHubAgentNewScreen";

const mockCreateHubAgentAdmin = jest.fn();
const mockCreateProxyAllowlistEntry = jest.fn();
const mockConfirmAction = jest.fn();
const mockInvalidateQueries = jest.fn();
const mockAllowNextNavigation = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();
const mockBackOrHome = jest.fn();
const mockRouter = {
  back: jest.fn(),
  replace: jest.fn(),
  canGoBack: jest.fn(() => true),
};

jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
}));

jest.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    invalidateQueries: mockInvalidateQueries,
  }),
}));

jest.mock("@/hooks/useRequireAdmin", () => ({
  useRequireAdmin: () => ({
    isReady: true,
    isAdmin: true,
  }),
}));

jest.mock("@/hooks/usePreventRemoveWhenDirty", () => ({
  usePreventRemoveWhenDirty: () => ({
    allowNextNavigation: mockAllowNextNavigation,
  }),
}));

jest.mock("@/lib/api/hubA2aAgentsAdmin", () => ({
  createHubAgentAdmin: (...args: unknown[]) => mockCreateHubAgentAdmin(...args),
}));

jest.mock("@/lib/api/adminProxyAllowlist", () => ({
  createProxyAllowlistEntry: (...args: unknown[]) =>
    mockCreateProxyAllowlistEntry(...args),
}));

jest.mock("@/lib/confirm", () => ({
  confirmAction: (...args: unknown[]) => mockConfirmAction(...args),
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

jest.mock("@/lib/navigation", () => ({
  backOrHome: (...args: unknown[]) => mockBackOrHome(...args),
}));

jest.mock("@/components/layout/ScreenContainer", () => ({
  ScreenContainer: ({ children }: { children: unknown }) => children,
}));

jest.mock("@/components/ui/PageHeader", () => ({
  PageHeader: () => null,
}));

jest.mock("@/components/ui/IconButton", () => ({
  IconButton: () => null,
}));

jest.mock("@/components/ui/FullscreenLoader", () => ({
  FullscreenLoader: () => null,
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

jest.mock("@/screens/admin/HubAgentFormSections", () => ({
  HubAgentFormSections: () => null,
}));

jest.mock("@/screens/admin/hubAgentFormState", () => ({
  useHubAgentFormState: () => ({
    values: {},
    errors: {},
    canSave: true,
    hasDraftInput: true,
    setName: jest.fn(),
    setCardUrl: jest.fn(),
    setEnabled: jest.fn(),
    setAvailabilityPolicy: jest.fn(),
    setAuthType: jest.fn(),
    setAuthHeader: jest.fn(),
    setAuthScheme: jest.fn(),
    setToken: jest.fn(),
    setTagsText: jest.fn(),
    setHeaderRow: jest.fn(),
    removeHeaderRow: jest.fn(),
    addHeaderRow: jest.fn(),
    validate: () => true,
    buildPayload: () => ({
      name: "Shared Agent",
      card_url: "https://blocked.example.com:8443/agent.json",
      availability_policy: "public",
      auth_type: "none",
      enabled: true,
      tags: [],
      extra_headers: {},
    }),
  }),
}));

describe("AdminHubAgentNewScreen auto allowlist create flow", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("allows admin shared-agent creation to auto-add host and retry create", async () => {
    mockCreateHubAgentAdmin
      .mockRejectedValueOnce(
        Object.assign(new Error("Card URL host is not allowed"), {
          status: 403,
          errorCode: "card_url_host_not_allowed",
        }),
      )
      .mockResolvedValueOnce({ id: "shared-1", name: "Shared Agent" });
    mockConfirmAction.mockResolvedValue(true);
    mockCreateProxyAllowlistEntry.mockResolvedValue({ id: "allow-1" });

    const screen = render(<AdminHubAgentNewScreen />);

    fireEvent.press(screen.getByText("Create"));

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
      expect(mockCreateHubAgentAdmin).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith(
        "Shared agent created",
        "Shared Agent",
      );
    });
  });
});
