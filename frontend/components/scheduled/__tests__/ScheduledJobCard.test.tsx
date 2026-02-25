import { fireEvent, render } from "@testing-library/react-native";
import { act, create } from "react-test-renderer";

import { ScheduledJobCard } from "@/components/scheduled/ScheduledJobCard";

jest.mock("expo-router", () => ({
  useRouter: () => ({
    push: jest.fn(),
  }),
}));

jest.mock("@/lib/focus", () => ({
  blurActiveElement: jest.fn(),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    error: jest.fn(),
  },
}));

jest.mock("@/components/ui/Button", () => {
  const { Pressable, Text } = require("react-native");
  return {
    Button: ({ label, onPress }: any) => (
      <Pressable onPress={onPress}>
        <Text>{label}</Text>
      </Pressable>
    ),
  };
});

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

describe("ScheduledJobCard visuals", () => {
  const defaultProps = {
    agentName: "Agent One",
    executions: [],
    executionsOpen: false,
    executionsLoading: false,
    onToggleEnabled: jest.fn(),
    onEdit: jest.fn(),
    onMarkFailed: jest.fn(),
    onToggleExecutions: jest.fn(),
  };

  it("applies blue styling when job is enabled and running", () => {
    const job = {
      id: "1",
      name: "Job",
      enabled: true,
      last_run_status: "running" as const,
      next_run_at: "2026-02-23T10:00:00Z",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    const containerClasses = tree.props.className;
    expect(containerClasses).toContain("bg-primary");
  });

  it("applies grayscale styling when job is disabled", () => {
    const job = {
      id: "2",
      name: "Job",
      enabled: false,
      last_run_status: "success" as const,
      next_run_at: "2026-02-23T10:00:00Z",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    const containerClasses = tree.props.className;
    expect(containerClasses).toContain("bg-gray-800/40");
  });

  it("applies default styling when job is enabled but not running", () => {
    const job = {
      id: "3",
      name: "Job",
      enabled: true,
      last_run_status: "success" as const,
      next_run_at: "2026-02-23T10:00:00Z",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    const containerClasses = tree.props.className;
    expect(containerClasses).toContain("bg-surface");
  });

  it("shows Stop Running button for running jobs", () => {
    const job = {
      id: "4",
      name: "Job",
      enabled: true,
      last_run_status: "running" as const,
      next_run_at: "2026-02-23T10:00:00Z",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    expect(JSON.stringify(tree)).toContain("Stop");
  });

  it("hides Stop Running button for non-running jobs", () => {
    const job = {
      id: "5",
      name: "Job",
      enabled: true,
      last_run_status: "success" as const,
      next_run_at: "2026-02-23T10:00:00Z",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    expect(JSON.stringify(tree)).not.toContain("Stop");
  });

  it("toggles prompt expansion with Read more and Show less", () => {
    const job = {
      id: "6",
      name: "Job",
      enabled: true,
      prompt:
        "This is a long scheduled prompt text used to verify expand and collapse behavior in card UI.",
      cycle_type: "daily" as const,
      time_point: { time: "09:00" },
      last_run_status: "success" as const,
      next_run_at: "2026-02-23T10:00:00Z",
    };
    const { getByLabelText, getByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    expect(getByText("Read more")).toBeTruthy();
    expect(getByText(job.prompt).props.numberOfLines).toBe(2);

    fireEvent.press(getByLabelText("Toggle prompt expansion"));

    expect(getByText("Show less")).toBeTruthy();
    expect(getByText(job.prompt).props.numberOfLines).toBeUndefined();
  });

  it("shows interval details including minutes and start time", () => {
    const job = {
      id: "7",
      name: "Interval Job",
      enabled: true,
      prompt: "Interval prompt",
      cycle_type: "interval" as const,
      time_point: {
        minutes: 15,
        start_at: "2026-02-23T10:00:00Z",
      },
      last_run_status: "success" as const,
      next_run_at: "2026-02-23T10:00:00Z",
    };
    const { getByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    expect(getByText(/Interval: every 15 min/)).toBeTruthy();
  });
});
