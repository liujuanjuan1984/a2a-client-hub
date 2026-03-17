import { fireEvent, render } from "@testing-library/react-native";
import React from "react";
import { TextInput } from "react-native";

import { ChatComposer } from "../ChatComposer";

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

describe("ChatComposer clear button", () => {
  const mockProps = {
    modelSelectionStatus: "supported" as const,
    pendingInterrupt: null,
    showShortcutManager: false,
    onOpenShortcutManager: jest.fn(),
    selectedModel: null,
    onOpenModelPicker: jest.fn(),
    inputRef: { current: { focus: jest.fn() } } as any,
    input: "",
    onInputChange: jest.fn(),
    onContentSizeChange: jest.fn(),
    inputHeight: 40,
    maxInputHeight: 200,
    onSubmit: jest.fn(),
    onKeyPress: jest.fn(),
  };

  it("does not show clear button when input is empty", () => {
    const { queryByLabelText } = render(<ChatComposer {...mockProps} />);
    expect(queryByLabelText("Clear input")).toBeNull();
  });

  it("shows clear button when input is not empty", () => {
    const { getByLabelText } = render(
      <ChatComposer {...mockProps} input="hello" />,
    );
    expect(getByLabelText("Clear input")).toBeTruthy();
  });

  it("calls onInputChange with empty string and focuses input when cleared", () => {
    const onInputChange = jest.fn();
    const focus = jest.fn();
    const inputRef = { current: { focus } };

    const { getByLabelText } = render(
      <ChatComposer
        {...mockProps}
        input="hello"
        onInputChange={onInputChange}
        inputRef={inputRef as any}
      />,
    );

    fireEvent.press(getByLabelText("Clear input"));

    expect(onInputChange).toHaveBeenCalledWith("");
    expect(focus).toHaveBeenCalled();
  });

  it("shows default model label and opens picker", () => {
    const onOpenModelPicker = jest.fn();
    const { getByLabelText, getByText } = render(
      <ChatComposer {...mockProps} onOpenModelPicker={onOpenModelPicker} />,
    );

    expect(getByText("Model: Default")).toBeTruthy();
    fireEvent.press(getByLabelText("Choose model"));
    expect(onOpenModelPicker).toHaveBeenCalled();
  });

  it("renders selected provider/model in button", () => {
    const { getByText } = render(
      <ChatComposer
        {...mockProps}
        selectedModel={{ providerID: "openai", modelID: "gpt-5" }}
      />,
    );

    expect(getByText("openai / gpt-5")).toBeTruthy();
  });

  it("hides model picker when capability is unsupported", () => {
    const { queryByLabelText } = render(
      <ChatComposer {...mockProps} modelSelectionStatus="unsupported" />,
    );

    expect(queryByLabelText("Choose model")).toBeNull();
  });

  it("keeps model picker visible when capability is still unknown", () => {
    const { getByA11yHint, getByLabelText } = render(
      <ChatComposer {...mockProps} modelSelectionStatus="unknown" />,
    );

    expect(getByLabelText("Choose model")).toBeTruthy();
    expect(
      getByA11yHint("Open the model picker and verify discovery availability."),
    ).toBeTruthy();
  });

  it("hides only the model picker while keeping other actions available on focus", () => {
    const { getByLabelText, queryByLabelText, UNSAFE_getByType } = render(
      <ChatComposer
        {...mockProps}
        input="hello"
        showScrollToBottom
        onScrollToBottom={jest.fn()}
      />,
    );

    fireEvent(UNSAFE_getByType(TextInput), "focus");

    expect(queryByLabelText("Choose model")).toBeNull();
    expect(getByLabelText("Open shortcut manager")).toBeTruthy();
    expect(getByLabelText("Clear input")).toBeTruthy();
    expect(getByLabelText("Scroll to bottom")).toBeTruthy();
  });
});
