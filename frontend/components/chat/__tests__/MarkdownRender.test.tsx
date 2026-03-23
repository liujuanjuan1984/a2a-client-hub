import { render } from "@testing-library/react-native";
import React from "react";

import { MarkdownRender } from "../MarkdownRender";

const mockMarkdown = jest.fn((props: unknown) => props);

jest.mock("react-native-markdown-display", () => {
  return {
    __esModule: true,
    default: (props: unknown) => {
      mockMarkdown(props);
      return null;
    },
  };
});

describe("MarkdownRender", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("provides divider styling for horizontal rules", () => {
    render(<MarkdownRender content={"before\n\n---\n\nafter"} isAgent />);

    expect(mockMarkdown).toHaveBeenCalledTimes(1);
    const props = mockMarkdown.mock.calls[0]?.[0] as unknown as {
      style: {
        hr: {
          backgroundColor: string;
          marginVertical: number;
        };
      };
    };

    expect(props.style.hr.backgroundColor).toBe("rgba(148, 163, 184, 0.24)");
    expect(props.style.hr.marginVertical).toBe(16);
  });

  it("uses the shared agent text token for markdown body text", () => {
    render(<MarkdownRender content="hello" isAgent />);

    const props = mockMarkdown.mock.calls[0]?.[0] as unknown as {
      style: {
        body: {
          color: string;
        };
      };
    };

    expect(props.style.body.color).toBe("#E2E8F0");
  });
});
