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

jest.mock("@/components/ui/IconButton", () => {
  const { Pressable, Text } = require("react-native");
  return {
    IconButton: ({ accessibilityLabel, className, onPress }: any) => (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel}
        className={className}
        onPress={onPress}
      >
        <Text>{accessibilityLabel}</Text>
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
      status_summary: {
        state: "running",
        manual_intervention_recommended: false,
        running_duration_seconds: 90,
      },
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
      status_summary: {
        state: "recent_failed",
        manual_intervention_recommended: false,
      },
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
      status_summary: {
        state: "idle",
        manual_intervention_recommended: false,
      },
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
      status_summary: {
        state: "running",
        manual_intervention_recommended: false,
      },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    let root: any;
    act(() => {
      root = create(<ScheduledJobCard {...defaultProps} job={job as any} />);
    });
    const tree = root.toJSON();
    expect(JSON.stringify(tree)).toContain("Stop run");
    expect(JSON.stringify(tree)).not.toContain("Edit");
    expect(JSON.stringify(tree)).not.toContain("Delete");
  });

  it("hides Stop Running button for non-running jobs", () => {
    const job = {
      id: "5",
      name: "Job",
      enabled: true,
      status_summary: {
        state: "idle",
        manual_intervention_recommended: false,
      },
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

  it("shows an attention hint and stalled stop label when heartbeat is stale", () => {
    const job = {
      id: "5a",
      name: "Job",
      enabled: true,
      is_running: true,
      status_summary: {
        state: "running",
        manual_intervention_recommended: true,
        last_heartbeat_at: "2026-02-23T09:00:00Z",
      },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    expect(getByText(/No heartbeat since/)).toBeTruthy();
    expect(getByText("Stop stalled run")).toBeTruthy();
  });

  it("applies a minimum touch target to icon-only actions", () => {
    const job = {
      id: "5b",
      name: "Job",
      enabled: true,
      prompt: "Prompt",
      status_summary: {
        state: "idle",
        manual_intervention_recommended: false,
      },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getByLabelText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    expect(getByLabelText("Edit job").props.className).toContain("min-h-10");
    expect(getByLabelText("Edit job").props.className).toContain("min-w-10");
    expect(getByLabelText("Delete job").props.className).toContain("min-h-10");
    expect(getByLabelText("Delete job").props.className).toContain("min-w-10");
  });

  it("toggles prompt expansion with the prompt icon button", () => {
    const job = {
      id: "6",
      name: "Job",
      enabled: true,
      prompt: "Scheduled prompt text",
      cycle_type: "daily" as const,
      time_point: { time: "09:00" },
      status_summary: {
        state: "idle",
        manual_intervention_recommended: false,
      },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getByLabelText, getByText, queryByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    // Prompt should be hidden by default
    expect(queryByText(job.prompt)).toBeNull();
    expect(getByLabelText("Expand prompt")).toBeTruthy();

    // Expand prompt
    fireEvent.press(getByLabelText("Expand prompt"));

    expect(getByText(job.prompt)).toBeTruthy();
    expect(getByLabelText("Collapse prompt")).toBeTruthy();

    // Collapse prompt
    fireEvent.press(getByLabelText("Collapse prompt"));
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
      status_summary: {
        state: "idle",
        manual_intervention_recommended: false,
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
      status_summary: {
        state: "idle",
        manual_intervention_recommended: false,
      },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const execution = {
      id: "execution-1",
      status: "success" as const,
      scheduled_for: "2026-02-23T10:00:00Z",
      started_at: "2026-02-23T10:00:00Z",
      finished_at: "2026-02-23T10:02:00Z",
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
    expect(JSON.stringify(root.toJSON())).toContain("Duration:");
    expect(JSON.stringify(root.toJSON())).not.toContain("upstream timeout");
  });

  it("formats next run timestamps as YYYY-MM-DD HH:mm", () => {
    const job = {
      id: "7aa",
      name: "Local Time Job",
      enabled: true,
      next_run_at_local: "2026-04-02T20:35",
      status_summary: {
        state: "idle",
        manual_intervention_recommended: false,
      },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-04-02T12:35:00Z",
      schedule_timezone: "UTC",
    };
    const { getByText, queryByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    expect(getByText(/Next:\s*2026-04-02 20:35/)).toBeTruthy();
    expect(queryByText(/Next:\s*2026-04-02T20:35/)).toBeNull();
  });

  it("renders execution error summary only when it exists", () => {
    const job = {
      id: "7b",
      name: "History Job",
      enabled: true,
      status_summary: {
        state: "recent_failed",
        manual_intervention_recommended: false,
        recent_failure_message: "upstream timeout",
      },
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
              error_code: "agent_unavailable",
              error_message: ` ${errorMessage} `,
            },
          ] as any
        }
        executionsOpen
      />,
    );

    expect(getByText("FAILED")).toBeTruthy();
    expect(getByText(errorMessage)).toBeTruthy();
    expect(getByText("Agent unavailable")).toBeTruthy();
  });

  it("renders recent failure hint with structured error code label", () => {
    const job = {
      id: "7d",
      name: "History Job",
      enabled: true,
      status_summary: {
        state: "recent_failed",
        manual_intervention_recommended: false,
        recent_failure_error_code: "outbound_not_allowed",
      },
      last_run_status: "failed" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getByText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    expect(getByText(/Outbound blocked/)).toBeTruthy();
  });

  it("shows heartbeat timing for running execution history rows", () => {
    const job = {
      id: "7c",
      name: "Running History Job",
      enabled: true,
      status_summary: {
        state: "running",
        manual_intervention_recommended: false,
      },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getAllByText, getByText } = render(
      <ScheduledJobCard
        {...defaultProps}
        job={job as any}
        executions={
          [
            {
              id: "execution-3",
              status: "running" as const,
              scheduled_for: "2026-02-23T10:00:00Z",
              started_at: "2026-02-23T10:00:00Z",
              last_heartbeat_at: "2026-02-23T10:01:00Z",
            },
          ] as any
        }
        executionsOpen
      />,
    );

    expect(getAllByText("RUNNING").length).toBeGreaterThanOrEqual(1);
    expect(getByText(/Last heartbeat:/)).toBeTruthy();
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
      status_summary: {
        state: "idle",
        manual_intervention_recommended: false,
      },
      last_run_status: "success" as const,
      next_run_at_utc: "2026-02-23T10:00:00Z",
      schedule_timezone: "UTC",
    };
    const { getByLabelText } = render(
      <ScheduledJobCard {...defaultProps} job={job as any} />,
    );

    await act(async () => {
      fireEvent.press(getByLabelText("Delete job"));
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
      status_summary: {
        state: "idle",
        manual_intervention_recommended: false,
      },
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
