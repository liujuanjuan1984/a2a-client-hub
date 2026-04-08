import { fireEvent, render } from "@testing-library/react-native";

import { AppRouteErrorBoundary } from "../AppRouteErrorBoundary";

jest.mock("@expo/vector-icons/Ionicons", () => () => null);

describe("AppRouteErrorBoundary", () => {
  it("renders fallback copy with the error message", () => {
    const screen = render(
      <AppRouteErrorBoundary
        error={new Error("route exploded")}
        retry={jest.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByText("Something went wrong")).toBeTruthy();
    expect(screen.getByText("route exploded")).toBeTruthy();
    expect(
      screen.getByText(
        "This screen crashed during rendering. Retry the route to recover.",
      ),
    ).toBeTruthy();
  });

  it("retries the route when the retry button is pressed", () => {
    const retry = jest.fn().mockResolvedValue(undefined);
    const screen = render(
      <AppRouteErrorBoundary error={new Error("retry me")} retry={retry} />,
    );

    fireEvent.press(screen.getByText("Retry"));

    expect(retry).toHaveBeenCalledTimes(1);
  });
});
