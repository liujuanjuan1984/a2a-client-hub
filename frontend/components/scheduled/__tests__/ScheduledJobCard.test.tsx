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
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    const containerClasses = tree.props.className;
    expect(containerClasses).toContain("border-primary");
  });

  it("applies grayscale styling when job is disabled", () => {
    const job = {
      id: "2",
      name: "Job",
      enabled: false,
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    const containerClasses = tree.props.className;
    expect(containerClasses).toContain("bg-surface");
    expect(containerClasses).toContain("opacity-80");
  });

  it("applies default styling when job is enabled but not running", () => {
    const job = {
      id: "3",
      name: "Job",
      enabled: true,
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
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
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
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
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    expect(JSON.stringify(tree)).not.toContain("Stop");
  });

  it("toggles prompt expansion with Show/Hide Prompt labels", () => {
    const job = {
      id: "6",
      name: "Job",
      enabled: true,
      prompt: "Scheduled prompt text",
      cycle_type: "daily" as const,
      time_point: { time: "09:00" },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getByText, queryByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    // Prompt should be hidden by default
    expect(queryByText(job.prompt)).toBeNull();
    expect(getByText("Show Prompt")).toBeTruthy();

    // Click Show Prompt to expand
    fireEvent.press(getByText("Show Prompt"));

    expect(getByText(job.prompt)).toBeTruthy();
    expect(getByText("Hide Prompt")).toBeTruthy();

    // Click Hide Prompt to collapse
    fireEvent.press(getByText("Hide Prompt"));
    expect(queryByText(job.prompt)).toBeNull();
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
        start_at_local: "2026-02-23T18:00",
        start_at_utc: "2026-02-23T10:00:00Z",
      },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    expect(getByText(/Every 15 min/)).toBeTruthy();
  });
});
