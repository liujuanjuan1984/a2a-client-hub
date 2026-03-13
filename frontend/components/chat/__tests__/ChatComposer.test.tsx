import { fireEvent, render } from "@testing-library/react-native";
import React from "react";

import { ChatComposer } from "../ChatComposer";

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

describe("ChatComposer clear button", () => {
  const mockProps = {
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
});
