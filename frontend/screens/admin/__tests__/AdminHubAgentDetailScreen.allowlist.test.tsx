import { fireEvent, render, waitFor } from "@testing-library/react-native";

import { AdminHubAgentDetailScreen } from "@/screens/admin/AdminHubAgentDetailScreen";

const mockUpdateHubAgentAdmin = jest.fn();
const mockDeleteHubAgentAdmin = jest.fn();
const mockCreateProxyAllowlistEntry = jest.fn();
const mockConfirmAction = jest.fn();
const mockInvalidateQueries = jest.fn();
const mockAllowNextNavigation = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();
const mockRefetch = jest.fn().mockResolvedValue({ data: null });
const mockAgentQueryData = {
  id: "shared-1",
  name: "Shared Agent",
  card_url: "https://existing.example.com/agent.json",
  availability_policy: "public",
  auth_type: "none",
  enabled: true,
  tags: [],
  extra_headers: {},
  invoke_metadata_defaults: {},
  has_credential: false,
  token_last4: null,
  created_by_user_id: "admin-1",
  updated_by_user_id: "admin-1",
  created_at: "2026-03-25T00:00:00Z",
  updated_at: "2026-03-25T00:00:00Z",
};
const mockRouter = {
  replace: jest.fn(),
  push: jest.fn(),
  canGoBack: jest.fn(() => true),
  back: jest.fn(),
};

jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
}));

jest.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    invalidateQueries: mockInvalidateQueries,
  }),
  useQuery: () => ({
    data: mockAgentQueryData,
    isRefetching: false,
    isError: false,
    error: null,
    refetch: mockRefetch,
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
  getHubAgentAdmin: jest.fn(),
  updateHubAgentAdmin: (...args: unknown[]) => mockUpdateHubAgentAdmin(...args),
  deleteHubAgentAdmin: (...args: unknown[]) => mockDeleteHubAgentAdmin(...args),
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
  backOrHome: jest.fn(),
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
  buildHubAgentComparablePayloadFromRecord: () => ({}),
  useHubAgentFormState: () => ({
    values: { availabilityPolicy: "public", authType: "none" },
    errors: {},
    canSave: true,
    comparablePayload: {},
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
    setInvokeMetadataDefaultRow: jest.fn(),
    removeInvokeMetadataDefaultRow: jest.fn(),
    addInvokeMetadataDefaultRow: jest.fn(),
    hydrateFromRecord: jest.fn(),
    validate: () => true,
    buildPayload: () => ({
      name: "Shared Agent",
      card_url: "https://blocked.example.com:8443/agent.json",
      availability_policy: "public",
      auth_type: "none",
      enabled: true,
      tags: [],
      extra_headers: {},
      invoke_metadata_defaults: {},
      token: null,
    }),
  }),
}));

describe("AdminHubAgentDetailScreen auto allowlist update flow", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("allows admin shared-agent updates to auto-add host and retry save", async () => {
    mockUpdateHubAgentAdmin
      .mockRejectedValueOnce(
        Object.assign(new Error("Card URL host is not allowed"), {
          status: 403,
          errorCode: "card_url_host_not_allowed",
        }),
      )
      .mockResolvedValueOnce({ id: "shared-1", name: "Shared Agent" });
    mockConfirmAction.mockResolvedValue(true);
    mockCreateProxyAllowlistEntry.mockResolvedValue({ id: "allow-1" });

    const screen = render(<AdminHubAgentDetailScreen agentId="shared-1" />);

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
        host_pattern: "blocked.example.com:8443",
      });
    });
    await waitFor(() => {
      expect(mockUpdateHubAgentAdmin).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith(
        "Saved",
        "Shared agent updated.",
      );
    });
    expect(mockInvalidateQueries).toHaveBeenCalledTimes(2);
    expect(mockAllowNextNavigation).toHaveBeenCalledTimes(1);
    expect(mockRouter.replace).toHaveBeenCalledWith("/admin/hub-a2a");
  });
});
