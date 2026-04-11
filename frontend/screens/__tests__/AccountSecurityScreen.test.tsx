import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { ApiRequestError } from "@/lib/api/client";
import { AccountSecurityScreen } from "@/screens/AccountSecurityScreen";
import { useSessionStore } from "@/store/session";

const mockReplace = jest.fn();
const mockBack = jest.fn();
const mockCanGoBack = jest.fn(() => false);
const mockChangePasswordMutateAsync = jest.fn();
const mockLogoutMutateAsync = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();
const mockResetAuthBoundState = jest.fn();
const mockBlurActiveElement = jest.fn();

let mockChangePasswordState = {
  isPending: false,
  error: null as unknown,
};

let mockLogoutState = {
  isPending: false,
};

jest.mock("expo-router", () => ({
  useRouter: () => ({
    replace: mockReplace,
    back: mockBack,
    canGoBack: mockCanGoBack,
  }),
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
  }),
}));

jest.mock("@/components/ui/Button", () => ({
  Button: "MockButton",
}));

jest.mock("@/components/ui/Input", () => ({
  Input: "MockInput",
}));

jest.mock("@/hooks/useAuth", () => ({
  useChangePassword: () => ({
    ...mockChangePasswordState,
    mutateAsync: (...args: unknown[]) => mockChangePasswordMutateAsync(...args),
  }),
  useLogout: () => ({
    ...mockLogoutState,
    mutateAsync: (...args: unknown[]) => mockLogoutMutateAsync(...args),
  }),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

jest.mock("@/lib/resetClientState", () => ({
  resetAuthBoundState: () => mockResetAuthBoundState(),
}));

jest.mock("@/lib/focus", () => ({
  blurActiveElement: () => mockBlurActiveElement(),
}));

describe("AccountSecurityScreen", () => {
  let tree: ReactTestRenderer | null = null;

  const renderScreen = async () => {
    await act(async () => {
      tree = create(<AccountSecurityScreen />);
    });
    return tree as ReactTestRenderer;
  };

  const getInputs = () => tree?.root.findAllByType("MockInput" as any) ?? [];

  const setInputValue = async (index: number, value: string) => {
    const input = getInputs()[index];
    await act(async () => {
      input.props.onChangeText(value);
    });
  };

  const pressButtonByText = async (label: string) => {
    const button = tree?.root
      .findAllByType("MockButton" as any)
      .find((candidate) => {
        return candidate.props.label === label;
      });

    if (!button) {
      throw new Error(`Button not found: ${label}`);
    }

    await act(async () => {
      button.props.onPress?.();
      await Promise.resolve();
    });
  };

  beforeEach(() => {
    mockReplace.mockReset();
    mockBack.mockReset();
    mockCanGoBack.mockReset();
    mockCanGoBack.mockReturnValue(false);
    mockChangePasswordMutateAsync.mockReset();
    mockLogoutMutateAsync.mockReset();
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
    mockResetAuthBoundState.mockReset();
    mockBlurActiveElement.mockReset();
    mockChangePasswordState = { isPending: false, error: null };
    mockLogoutState = { isPending: false };
    tree = null;

    act(() => {
      useSessionStore.setState({
        user: {
          id: "user-1",
          email: "user@example.com",
          name: "Test User",
          is_superuser: false,
          timezone: "UTC",
        },
      });
    });
  });

  afterEach(async () => {
    if (!tree) {
      return;
    }
    await act(async () => {
      tree?.unmount();
      tree = null;
    });
  });

  it("submits password change and signs the user out on success", async () => {
    mockChangePasswordMutateAsync.mockResolvedValue({
      message: "Password updated successfully",
    });

    await renderScreen();

    await setInputValue(0, "OldPass!23");
    await setInputValue(1, "NewPass!23");
    await setInputValue(2, "NewPass!23");
    await pressButtonByText("Change Password");

    expect(mockChangePasswordMutateAsync).toHaveBeenCalledWith({
      current_password: "OldPass!23", // pragma: allowlist secret
      new_password: "NewPass!23", // pragma: allowlist secret
      new_password_confirm: "NewPass!23", // pragma: allowlist secret
    });
    expect(mockToastSuccess).toHaveBeenCalledWith(
      "Password updated",
      "Please sign in again.",
    );
    expect(mockResetAuthBoundState).toHaveBeenCalledTimes(1);
    expect(mockReplace).toHaveBeenCalledWith("/login");
  });

  it("blocks password change when confirmation does not match", async () => {
    await renderScreen();

    await setInputValue(0, "OldPass!23");
    await setInputValue(1, "NewPass!23");
    await setInputValue(2, "Mismatch!23");
    await pressButtonByText("Change Password");

    expect(mockChangePasswordMutateAsync).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledWith(
      "Validation failed",
      "Password confirmation does not match.",
    );
    expect(mockResetAuthBoundState).not.toHaveBeenCalled();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("forces local sign-out when logout returns an auth failure", async () => {
    mockLogoutMutateAsync.mockRejectedValue(
      new ApiRequestError("Authentication expired. Please sign in again.", 401),
    );

    await renderScreen();
    await pressButtonByText("Logout");

    expect(mockLogoutMutateAsync).toHaveBeenCalledTimes(1);
    expect(mockResetAuthBoundState).toHaveBeenCalledTimes(1);
    expect(mockReplace).toHaveBeenCalledWith("/login");
    expect(mockToastError).not.toHaveBeenCalled();
  });
});
