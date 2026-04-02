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
    currentDirectory: null,
    hasInvokeMetadata: false,
    invokeMetadataRequiredCount: 0,
    pendingInterrupt: null,
    pendingInterruptCount: 0,
    showShortcutManager: false,
    onOpenDirectoryPicker: jest.fn(),
    onOpenInvokeMetadata: jest.fn(),
    onOpenShortcutManager: jest.fn(),
    selectedModel: null,
    onOpenModelPicker: jest.fn(),
    inputRef: { current: { focus: jest.fn() } } as any,
    inputResetKey: 0,
    inputDefaultValue: "",
    inputSelection: null,
    hasInput: false,
    hasSendableInput: false,
    maxInputChars: 50_000,
    onClearInput: jest.fn(),
    onInputChange: jest.fn(),
    onSelectionChange: jest.fn(),
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
      <ChatComposer
        {...mockProps}
        inputDefaultValue="hello"
        hasInput
        hasSendableInput
      />,
    );
    expect(getByLabelText("Clear input")).toBeTruthy();
  });

  it("calls onClearInput when cleared", () => {
    const onClearInput = jest.fn();

    const { getByLabelText } = render(
      <ChatComposer
        {...mockProps}
        inputDefaultValue="hello"
        hasInput
        hasSendableInput
        onClearInput={onClearInput}
      />,
    );

    fireEvent.press(getByLabelText("Clear input"));

    expect(onClearInput).toHaveBeenCalled();
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

  it("opens the working directory modal", () => {
    const onOpenDirectoryPicker = jest.fn();
    const { getByLabelText } = render(
      <ChatComposer
        {...mockProps}
        onOpenDirectoryPicker={onOpenDirectoryPicker}
      />,
    );

    fireEvent.press(getByLabelText("Configure working directory"));
    expect(onOpenDirectoryPicker).toHaveBeenCalled();
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
        hasInput
        hasSendableInput
        inputDefaultValue="hello"
        showScrollToBottom
        onScrollToBottom={jest.fn()}
      />,
    );

    fireEvent(UNSAFE_getByType(TextInput), "focus");

    expect(queryByLabelText("Choose model")).toBeNull();
    expect(getByLabelText("Configure working directory")).toBeTruthy();
    expect(getByLabelText("Open shortcut manager")).toBeTruthy();
    expect(getByLabelText("Clear input")).toBeTruthy();
    expect(getByLabelText("Scroll to bottom")).toBeTruthy();
  });

  it("applies the configured maxLength to the input", () => {
    const { UNSAFE_getByType } = render(<ChatComposer {...mockProps} />);

    expect(UNSAFE_getByType(TextInput).props.maxLength).toBe(50_000);
  });

  it("passes the requested caret position to the input selection", () => {
    const { UNSAFE_getByType } = render(
      <ChatComposer
        {...mockProps}
        inputDefaultValue="Shortcut prompt"
        inputSelection={{ start: 15, end: 15 }}
      />,
    );

    expect(UNSAFE_getByType(TextInput).props.selection).toEqual({
      start: 15,
      end: 15,
    });
  });
});
