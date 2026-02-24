import {
  DEFAULT_TIME_ZONE,
  formatLocalDateTime,
  formatLocalDateTimeYmdHm,
  formatDateTimeLocalInputValue,
  getNextTopOfHourLocalInputValue,
  localDateTimeInputToUtcIso,
  resolveUserTimeZone,
} from "@/lib/datetime";

describe("datetime helpers", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("uses resolved timezone when available", () => {
    jest
      .spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions")
      .mockReturnValue({
        timeZone: "UTC",
      } as Intl.ResolvedDateTimeFormatOptions);

    expect(resolveUserTimeZone()).toBe("UTC");
  });

  it("falls back to UTC when timezone is missing", () => {
    jest
      .spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions")
      .mockReturnValue({ timeZone: "" } as Intl.ResolvedDateTimeFormatOptions);

    expect(resolveUserTimeZone()).toBe(DEFAULT_TIME_ZONE);
  });

  it("falls back to UTC when timezone is invalid", () => {
    jest
      .spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions")
      .mockReturnValue({
        timeZone: "Invalid/Timezone",
      } as Intl.ResolvedDateTimeFormatOptions);

    expect(resolveUserTimeZone()).toBe(DEFAULT_TIME_ZONE);
  });

  it("formats timestamps consistently as YYYY-MM-DD HH:mm", () => {
    jest
      .spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions")
      .mockReturnValue({
        timeZone: "UTC",
      } as Intl.ResolvedDateTimeFormatOptions);

    expect(formatLocalDateTime("2026-02-12T07:08:30Z")).toBe(
      "2026-02-12 07:08",
    );
    expect(formatLocalDateTimeYmdHm("2026-02-12T07:08:30Z")).toBe(
      "2026-02-12 07:08",
    );
  });

  it("returns placeholders and passthrough values for empty or invalid input", () => {
    expect(formatLocalDateTime()).toBe("-");
    expect(formatLocalDateTime(null)).toBe("-");
    expect(formatLocalDateTime("not-a-date")).toBe("not-a-date");
  });

  it("formats datetime for local datetime input controls", () => {
    const source = "2026-02-23T09:30:15Z";
    const date = new Date(source);
    const pad2 = (value: number) => String(value).padStart(2, "0");
    const expected = `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(
      date.getDate(),
    )}T${pad2(date.getHours())}:${pad2(date.getMinutes())}`;

    expect(formatDateTimeLocalInputValue(source)).toBe(expected);
    expect(
      formatDateTimeLocalInputValue(
        "2026-02-23T00:15:00+00:00",
        "Asia/Shanghai",
      ),
    ).toBe("2026-02-23T08:15");
    expect(formatDateTimeLocalInputValue("bad-date")).toBe("");
  });

  it("normalizes local datetime input for backend payload", () => {
    expect(localDateTimeInputToUtcIso("2026-02-23T09:30", "UTC")).toBe(
      "2026-02-23T09:30:00.000Z",
    );
    expect(localDateTimeInputToUtcIso("2026-02-23 09:30", "UTC")).toBe(
      "2026-02-23T09:30:00.000Z",
    );
    expect(localDateTimeInputToUtcIso("2026-02-23T09:30:00+08:00")).toBe(
      "2026-02-23T01:30:00.000Z",
    );
    expect(localDateTimeInputToUtcIso("bad-datetime")).toBeNull();
    expect(localDateTimeInputToUtcIso("2026-02-30T09:30", "UTC")).toBeNull();
  });

  it("rejects DST-gap local datetime in timezone-aware validation", () => {
    expect(
      localDateTimeInputToUtcIso("2026-03-08T02:30", "America/New_York"),
    ).toBeNull();
    expect(
      localDateTimeInputToUtcIso("2026-03-08T02:30", "Asia/Shanghai"),
    ).toBe("2026-03-07T18:30:00.000Z");
  });

  it("accepts repeated local datetime during DST fall-back", () => {
    expect(
      localDateTimeInputToUtcIso("2026-11-01T01:30", "America/New_York"),
    ).toBe("2026-11-01T05:30:00.000Z");
  });

  it("builds next top-of-hour local input default", () => {
    expect(
      getNextTopOfHourLocalInputValue("UTC", new Date("2026-02-23T09:37:12Z")),
    ).toBe("2026-02-23T10:00");
    expect(
      getNextTopOfHourLocalInputValue(
        "UTC",
        new Date("2026-02-23T23:05:00.000Z"),
      ),
    ).toBe("2026-02-24T00:00");
    expect(
      getNextTopOfHourLocalInputValue(
        "Asia/Shanghai",
        new Date("2026-02-23T00:20:00.000Z"),
      ),
    ).toBe("2026-02-23T09:00");
    expect(
      getNextTopOfHourLocalInputValue(
        "America/New_York",
        new Date("2026-03-08T06:30:00.000Z"),
      ),
    ).toBe("2026-03-08T03:00");
  });
});
