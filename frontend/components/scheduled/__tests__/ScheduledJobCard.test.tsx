import { fireEvent, render } from "@testing-library/react-native";
import * as Clipboard from "expo-clipboard";
import { act, create } from "react-test-renderer";

import { ScheduledJobCard } from "@/components/scheduled/ScheduledJobCard";
import { toast } from "@/lib/toast";

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
    success: jest.fn(),
  },
}));

jest.mock("expo-clipboard", () => ({
  setStringAsync: jest.fn(() => Promise.resolve()),
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
    onDelete: jest.fn(),
    onMarkFailed: jest.fn(),
    onToggleExecutions: jest.fn(),
  };

  it("applies blue styling when job is enabled and running", () => {
    const job = {
      id: "1",
      name: "Job",
      enabled: true,
      is_running: true,
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
      is_running: true,
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    expect(JSON.stringify(tree)).toContain("Stop");
    expect(JSON.stringify(tree)).not.toContain("Edit");
    expect(JSON.stringify(tree)).not.toContain("Delete");
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

  it("toggles prompt expansion with More/Less labels", () => {
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
    expect(getByText("More")).toBeTruthy();

    // Click More to expand
    fireEvent.press(getByText("More"));

    expect(getByText(job.prompt)).toBeTruthy();
    expect(getByText("Less")).toBeTruthy();

    // Click Less to collapse
    fireEvent.press(getByText("Less"));
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

  it("renders execution history as a single main row when no error summary exists", () => {
    const job = {
      id: "7a",
      name: "History Job",
      enabled: true,
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const execution = {
      id: "execution-1",
      status: "success" as const,
      scheduled_for: "2026-02-23T10:00:00Z",
      conversation_id: "conversation-1",
    };
    let root: any;

    act(() => {
      root = create(
        <ScheduledJobCard
          {...defaultProps}
          job={job as any}
          executions={[execution] as any}
          executionsOpen
        />,
      );
    });

    expect(JSON.stringify(root.toJSON())).toContain("SUCCESS");
    expect(JSON.stringify(root.toJSON())).toContain("Open Session");
    expect(JSON.stringify(root.toJSON())).not.toContain("upstream timeout");
  });

  it("renders execution error summary only when it exists", () => {
    const job = {
      id: "7b",
      name: "History Job",
      enabled: true,
      last_run_status: "failed" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const errorMessage = "upstream timeout";
    const { getByText } = render(
      <ScheduledJobCard
        {...defaultProps}
        job={job as any}
        executions={
          [
            {
              id: "execution-2",
              status: "failed" as const,
              scheduled_for: "2026-02-23T10:00:00Z",
              error_message: ` ${errorMessage} `,
            },
          ] as any
        }
        executionsOpen
      />,
    );

    expect(getByText("FAILED")).toBeTruthy();
    expect(getByText(errorMessage)).toBeTruthy();
  });
});

jest.mock("@/lib/confirm", () => ({
  confirmAction: jest.fn(() => Promise.resolve(true)),
}));

describe("ScheduledJobCard interactions", () => {
  const defaultProps = {
    agentName: "Agent One",
    executions: [],
    executionsOpen: false,
    executionsLoading: false,
    onToggleEnabled: jest.fn(),
    onEdit: jest.fn(),
    onDelete: jest.fn(),
    onMarkFailed: jest.fn(),
    onToggleExecutions: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("calls onDelete when Delete button is pressed and confirmed", async () => {
    const job = {
      id: "8",
      name: "Job",
      enabled: true,
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    await act(async () => {
      fireEvent.press(getByText("Delete"));
    });

    expect(defaultProps.onDelete).toHaveBeenCalled();
  });

  it("copies prompt from the action bar without expanding the prompt area", async () => {
    const job = {
      id: "9",
      name: "Job",
      enabled: true,
      prompt: "Prompt ready to copy",
      cycle_type: "daily" as const,
      time_point: { time: "09:00" },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getByLabelText, queryByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    expect(queryByText(job.prompt)).toBeNull();

    await act(async () => {
      fireEvent.press(getByLabelText("Copy prompt"));
    });

    expect(Clipboard.setStringAsync).toHaveBeenCalledWith(job.prompt);
    expect(toast.success).toHaveBeenCalledWith(
      "Copied",
      "Prompt copied to clipboard.",
    );
  });
});
