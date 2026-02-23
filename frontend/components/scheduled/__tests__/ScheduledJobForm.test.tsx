import { fireEvent, render } from "@testing-library/react-native";

import type { ScheduledJobPayload } from "@/lib/api/scheduledJobs";
import { ScheduledJobForm } from "../ScheduledJobForm";

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
});
