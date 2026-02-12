import {
  DEFAULT_TIME_ZONE,
  formatLocalDateTime,
  formatLocalDateTimeYmdHm,
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
});
