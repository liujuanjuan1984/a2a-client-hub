import { fireEvent, render } from "@testing-library/react-native";

import { ScheduledJobForm } from "../ScheduledJobForm";

import type { ScheduledJobPayload } from "@/lib/api/scheduledJobs";

describe("ScheduledJobForm", () => {
  const basePayload: ScheduledJobPayload = {
    name: "",
    agent_id: "",
    prompt: "",
    cycle_type: "interval",
    time_point: {
      minutes: 10,
    },
    enabled: true,
    conversation_policy: "new_each_run",
  };

  it("preserves typed characters while editing start datetime input", () => {
    const onChange = jest.fn();
    const { getByPlaceholderText } = render(
      <ScheduledJobForm
        form={basePayload}
        saving={false}
        editing={false}
        agentOptions={[]}
        onChange={onChange}
        onSubmit={() => undefined}
        onCancel={() => undefined}
        timeZone="UTC"
      />,
    );

    const input = getByPlaceholderText("2026-02-23T14:30");
    fireEvent.changeText(input, "2");
    fireEvent.changeText(input, "20");
    fireEvent.changeText(input, "2026-02-23T09:30");

    expect(input.props.value).toBe("2026-02-23T09:30");
    expect(onChange).toHaveBeenLastCalledWith({
      time_point: {
        minutes: 10,
        start_at: "2026-02-23T09:30",
      },
    });
  });

  it("preserves pasted datetime text without timezone shift", () => {
    const onChange = jest.fn();
    const { getByPlaceholderText } = render(
      <ScheduledJobForm
        form={basePayload}
        saving={false}
        editing={false}
        agentOptions={[]}
        onChange={onChange}
        onSubmit={() => undefined}
        onCancel={() => undefined}
        timeZone="Asia/Shanghai"
      />,
    );

    const input = getByPlaceholderText("2026-02-23T14:30");
    fireEvent.changeText(input, "2026-02-23T12:35");

    expect(input.props.value).toBe("2026-02-23T12:35");
    expect(onChange).toHaveBeenLastCalledWith({
      time_point: {
        minutes: 10,
        start_at: "2026-02-23T12:35",
      },
    });
  });

  it("fills default start datetime when switching to interval", () => {
    const onChange = jest.fn();
    const form: ScheduledJobPayload = {
      ...basePayload,
      cycle_type: "daily",
      time_point: { time: "07:00" },
    };
    const { getByText } = render(
      <ScheduledJobForm
        form={form}
        saving={false}
        editing={false}
        agentOptions={[]}
        onChange={onChange}
        onSubmit={() => undefined}
        onCancel={() => undefined}
        timeZone="UTC"
      />,
    );

    fireEvent.press(getByText("Interval"));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0]?.[0]?.cycle_type).toBe("interval");
    expect(onChange.mock.calls[0]?.[0]?.time_point?.minutes).toBe(10);
    expect(
      String(onChange.mock.calls[0]?.[0]?.time_point?.start_at ?? ""),
    ).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:00$/);
  });
});
