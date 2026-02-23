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

jest.mock("@/components/ui/Button", () => ({
  Button: () => null,
}));

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
    expect(containerClasses).toContain("border-blue-500/50");
    expect(containerClasses).toContain("bg-blue-900/20");
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
    expect(containerClasses).toContain("grayscale");
    expect(containerClasses).toContain("bg-slate-900/10");
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
    expect(containerClasses).toContain("border-slate-800");
    expect(containerClasses).toContain("bg-slate-900/30");
  });
});
