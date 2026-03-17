import { fireEvent, render } from "@testing-library/react-native";
import React from "react";
import { Switch } from "react-native";

import { HubAgentFormSections } from "@/screens/admin/HubAgentFormSections";

jest.mock("@/components/ui/Input", () => ({
  Input: ({
    label,
    placeholder,
    value,
    onChangeText,
  }: {
    label: string;
    placeholder?: string;
    value?: string;
    onChangeText?: (value: string) => void;
  }) => {
    const React = require("react");
    const { Text, TextInput } = require("react-native");
    return (
      <>
        <Text>{label}</Text>
        <TextInput
          accessibilityLabel={label}
          placeholder={placeholder}
          value={value}
          onChangeText={onChangeText}
        />
      </>
    );
  },
}));

jest.mock("@/components/ui/Button", () => ({
  Button: ({ label, onPress }: { label: string; onPress?: () => void }) => {
    const React = require("react");
    const { Pressable, Text } = require("react-native");
    return (
      <Pressable accessibilityRole="button" onPress={onPress}>
        <Text>{label}</Text>
      </Pressable>
    );
  },
}));

jest.mock("@/components/ui/KeyValueInputRow", () => ({
  KeyValueInputRow: ({
    onChangeKey,
    onChangeValue,
    onRemove,
  }: {
    onChangeKey?: (value: string) => void;
    onChangeValue?: (value: string) => void;
    onRemove?: () => void;
  }) => {
    const React = require("react");
    const { Pressable, Text } = require("react-native");
    return (
      <>
        <Pressable onPress={() => onChangeKey?.("x-api-key")}>
          <Text>Change header key</Text>
        </Pressable>
        <Pressable onPress={() => onChangeValue?.("secret")}>
          <Text>Change header value</Text>
        </Pressable>
        <Pressable onPress={onRemove}>
          <Text>Remove header</Text>
        </Pressable>
      </>
    );
  },
}));

describe("HubAgentFormSections", () => {
  const baseProps = {
    values: {
      name: "Shared Agent",
      cardUrl: "https://agent.example.com/.well-known/agent.json",
      enabled: true,
      availabilityPolicy: "public" as const,
      authType: "none" as const,
      authHeader: "Authorization",
      authScheme: "Bearer",
      token: "",
      tagsText: "",
      extraHeaders: [{ id: "row-1", key: "", value: "" }],
    },
    errors: {},
    tokenLabel: "Token",
    tokenPlaceholder: "Enter token",
    onNameChange: jest.fn(),
    onCardUrlChange: jest.fn(),
    onEnabledChange: jest.fn(),
    onAvailabilityPolicyChange: jest.fn(),
    onAuthTypeChange: jest.fn(),
    onAuthHeaderChange: jest.fn(),
    onAuthSchemeChange: jest.fn(),
    onTokenChange: jest.fn(),
    onTagsTextChange: jest.fn(),
    onHeaderRowChange: jest.fn(),
    onHeaderRowRemove: jest.fn(),
    onHeaderRowAdd: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders generic metadata placeholder and forwards tag edits", () => {
    const screen = render(<HubAgentFormSections {...baseProps} />);

    expect(
      screen.getByPlaceholderText("e.g., coding, internal, research"),
    ).toBeTruthy();

    fireEvent.changeText(
      screen.getByLabelText("Tags (comma separated)"),
      "research, internal",
    );

    expect(baseProps.onTagsTextChange).toHaveBeenCalledWith(
      "research, internal",
    );
  });

  it("forwards enabled toggle and add-header actions", () => {
    const screen = render(<HubAgentFormSections {...baseProps} />);

    fireEvent(screen.UNSAFE_getByType(Switch), "valueChange", false);
    fireEvent.press(screen.getByText("Add header"));

    expect(baseProps.onEnabledChange).toHaveBeenCalledWith(false);
    expect(baseProps.onHeaderRowAdd).toHaveBeenCalled();
  });

  it("renders optional descriptions and forwards bearer plus header-row edits", () => {
    const screen = render(
      <HubAgentFormSections
        {...baseProps}
        values={{
          ...baseProps.values,
          availabilityPolicy: "allowlist",
          authType: "bearer",
          token: "abc",
        }}
        availabilityDescription="Restrict exposure."
        availabilityHintWhenAllowlist="Only allowlisted users can access this agent."
        authenticationDescription="Use bearer auth for upstream requests."
        tokenFootnote={<>Stored securely.</>}
        extraHeadersDescription="Forwarded to upstream requests."
      />,
    );

    expect(screen.getByText("Restrict exposure.")).toBeTruthy();
    expect(
      screen.getByText("Only allowlisted users can access this agent."),
    ).toBeTruthy();
    expect(
      screen.getByText("Use bearer auth for upstream requests."),
    ).toBeTruthy();
    expect(screen.getByText("Forwarded to upstream requests.")).toBeTruthy();

    fireEvent.press(screen.getByLabelText("Public"));
    fireEvent.press(screen.getByLabelText("No Auth"));
    fireEvent.changeText(screen.getByLabelText("Auth header"), "X-Auth");
    fireEvent.changeText(screen.getByLabelText("Auth scheme"), "Token");
    fireEvent.changeText(screen.getByLabelText("Token"), "next-token");
    fireEvent.press(screen.getByText("Change header key"));
    fireEvent.press(screen.getByText("Change header value"));
    fireEvent.press(screen.getByText("Remove header"));

    expect(baseProps.onAvailabilityPolicyChange).toHaveBeenCalledWith("public");
    expect(baseProps.onAuthTypeChange).toHaveBeenCalledWith("none");
    expect(baseProps.onAuthHeaderChange).toHaveBeenCalledWith("X-Auth");
    expect(baseProps.onAuthSchemeChange).toHaveBeenCalledWith("Token");
    expect(baseProps.onTokenChange).toHaveBeenCalledWith("next-token");
    expect(baseProps.onHeaderRowChange).toHaveBeenCalledWith(
      "row-1",
      "key",
      "x-api-key",
    );
    expect(baseProps.onHeaderRowChange).toHaveBeenCalledWith(
      "row-1",
      "value",
      "secret",
    );
    expect(baseProps.onHeaderRowRemove).toHaveBeenCalledWith("row-1");
  });
});
