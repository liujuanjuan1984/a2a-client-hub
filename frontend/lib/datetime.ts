const DATE_TIME_PLACEHOLDER = "-";
const DATE_LOCALE = "en-CA";

export const DEFAULT_TIME_ZONE = "UTC";

const FORMATTER_OPTIONS: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
};

const FORMATTER_WITH_SECONDS_OPTIONS: Intl.DateTimeFormatOptions = {
  ...FORMATTER_OPTIONS,
  second: "2-digit",
};

const formatterByTimeZone = new Map<string, Intl.DateTimeFormat>();
const formatterWithSecondsByTimeZone = new Map<string, Intl.DateTimeFormat>();

const getFormatter = (timeZone: string): Intl.DateTimeFormat => {
  const cached = formatterByTimeZone.get(timeZone);
  if (cached) {
    return cached;
  }
  const formatter = new Intl.DateTimeFormat(DATE_LOCALE, {
    ...FORMATTER_OPTIONS,
    timeZone,
  });
  formatterByTimeZone.set(timeZone, formatter);
  return formatter;
};

const getFormatterWithSeconds = (timeZone: string): Intl.DateTimeFormat => {
  const cached = formatterWithSecondsByTimeZone.get(timeZone);
  if (cached) {
    return cached;
  }
  const formatter = new Intl.DateTimeFormat(DATE_LOCALE, {
    ...FORMATTER_WITH_SECONDS_OPTIONS,
    timeZone,
  });
  formatterWithSecondsByTimeZone.set(timeZone, formatter);
  return formatter;
};

const isValidTimeZone = (timeZone: string): boolean => {
  try {
    getFormatter(timeZone).format(new Date());
    return true;
  } catch {
    return false;
  }
};

const normalizeTimeZone = (value: unknown): string | null => {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return isValidTimeZone(trimmed) ? trimmed : null;
};

export const resolveUserTimeZone = (): string => {
  try {
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return normalizeTimeZone(timeZone) ?? DEFAULT_TIME_ZONE;
  } catch {
    return DEFAULT_TIME_ZONE;
  }
};

type DateTimeParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

const parseDateTimeParts = (
  parts: Intl.DateTimeFormatPart[],
): DateTimeParts | null => {
  const values = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  const year = Number.parseInt(values.year ?? "", 10);
  const month = Number.parseInt(values.month ?? "", 10);
  const day = Number.parseInt(values.day ?? "", 10);
  const hour = Number.parseInt(values.hour ?? "", 10);
  const minute = Number.parseInt(values.minute ?? "", 10);
  const second = Number.parseInt(values.second ?? "0", 10);

  if (
    !Number.isFinite(year) ||
    !Number.isFinite(month) ||
    !Number.isFinite(day) ||
    !Number.isFinite(hour) ||
    !Number.isFinite(minute) ||
    !Number.isFinite(second)
  ) {
    return null;
  }
  return { year, month, day, hour, minute, second };
};

const toDateTimeParts = (date: Date, timeZone: string): DateTimeParts | null =>
  parseDateTimeParts(getFormatterWithSeconds(timeZone).formatToParts(date));

const pad2 = (value: number): string => String(value).padStart(2, "0");

const toYmdHm = (date: Date, timeZone: string): string => {
  const values = toDateTimeParts(date, timeZone);
  if (!values) {
    return date.toISOString().slice(0, 16).replace("T", " ");
  }
  return `${values.year}-${pad2(values.month)}-${pad2(values.day)} ${pad2(values.hour)}:${pad2(values.minute)}`;
};

const dateTimePartsToComparableMs = (parts: DateTimeParts): number =>
  Date.UTC(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute,
    parts.second,
    0,
  );

const hasValidCalendarDateTime = (parts: DateTimeParts): boolean => {
  const candidate = new Date(
    Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
      0,
    ),
  );
  return (
    candidate.getUTCFullYear() === parts.year &&
    candidate.getUTCMonth() === parts.month - 1 &&
    candidate.getUTCDate() === parts.day &&
    candidate.getUTCHours() === parts.hour &&
    candidate.getUTCMinutes() === parts.minute &&
    candidate.getUTCSeconds() === parts.second
  );
};

const DATE_TIME_INPUT_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?$/;
const DATE_TIME_OFFSET_SUFFIX_PATTERN = /(?:Z|[+-]\d{2}:\d{2})$/;

const parseDateTimeInputParts = (value: string): DateTimeParts | null => {
  const match = value.match(DATE_TIME_INPUT_PATTERN);
  if (!match) {
    return null;
  }

  const parts: DateTimeParts = {
    year: Number.parseInt(match[1], 10),
    month: Number.parseInt(match[2], 10),
    day: Number.parseInt(match[3], 10),
    hour: Number.parseInt(match[4], 10),
    minute: Number.parseInt(match[5], 10),
    second: Number.parseInt(match[6] ?? "0", 10),
  };

  if (
    !Number.isFinite(parts.year) ||
    !Number.isFinite(parts.month) ||
    !Number.isFinite(parts.day) ||
    !Number.isFinite(parts.hour) ||
    !Number.isFinite(parts.minute) ||
    !Number.isFinite(parts.second)
  ) {
    return null;
  }

  if (parts.month < 1 || parts.month > 12) return null;
  if (parts.day < 1 || parts.day > 31) return null;
  if (parts.hour < 0 || parts.hour > 23) return null;
  if (parts.minute < 0 || parts.minute > 59) return null;
  if (parts.second < 0 || parts.second > 59) return null;

  if (!hasValidCalendarDateTime(parts)) {
    return null;
  }

  return parts;
};

const isSameDateTimeParts = (
  left: DateTimeParts,
  right: DateTimeParts,
): boolean =>
  left.year === right.year &&
  left.month === right.month &&
  left.day === right.day &&
  left.hour === right.hour &&
  left.minute === right.minute &&
  left.second === right.second;

const resolveLocalDateTimeToUtcDate = (
  parts: DateTimeParts,
  timeZone: string,
): Date | null => {
  // Iteratively solve for the UTC instant that renders to the target wall-clock
  // datetime in the requested IANA timezone.
  let guessMs = dateTimePartsToComparableMs(parts);
  for (let index = 0; index < 8; index += 1) {
    const guessDate = new Date(guessMs);
    const localParts = toDateTimeParts(guessDate, timeZone);
    if (!localParts) {
      return null;
    }
    const deltaMs =
      dateTimePartsToComparableMs(parts) -
      dateTimePartsToComparableMs(localParts);
    if (deltaMs === 0) {
      return guessDate;
    }
    guessMs += deltaMs;
  }

  const resolved = new Date(guessMs);
  const resolvedLocalParts = toDateTimeParts(resolved, timeZone);
  if (!resolvedLocalParts || !isSameDateTimeParts(parts, resolvedLocalParts)) {
    return null;
  }
  return resolved;
};

export const formatLocalDateTime = (
  value?: string | null,
  timeZone?: string,
): string => {
  if (!value) return DATE_TIME_PLACEHOLDER;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const resolved = normalizeTimeZone(timeZone) ?? resolveUserTimeZone();
  return toYmdHm(date, resolved);
};

export const formatLocalDateTimeYmdHm = (value?: string | null): string =>
  formatLocalDateTime(value);

export const formatDateTimeLocalInputValue = (
  value?: string | null,
  timeZone?: string,
): string => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const resolved = normalizeTimeZone(timeZone) ?? resolveUserTimeZone();
  const display = toYmdHm(date, resolved).replace(" ", "T");
  return display;
};

export const getNextTopOfHourLocalInputValue = (
  timeZone?: string,
  now: Date = new Date(),
): string => {
  const resolved = normalizeTimeZone(timeZone) ?? resolveUserTimeZone();
  let cursor = new Date(now.getTime());
  cursor.setUTCSeconds(0, 0);
  cursor = new Date(cursor.getTime() + 60_000);

  // Scan forward at minute resolution and pick the first valid local HH:00.
  for (let index = 0; index < 36 * 60; index += 1) {
    const localParts = toDateTimeParts(cursor, resolved);
    if (localParts && localParts.minute === 0) {
      return `${localParts.year}-${pad2(localParts.month)}-${pad2(localParts.day)}T${pad2(localParts.hour)}:00`;
    }
    cursor = new Date(cursor.getTime() + 60_000);
  }

  const fallback = new Date(now.getTime());
  fallback.setMinutes(0, 0, 0);
  fallback.setHours(fallback.getHours() + 1);
  return fallback.toISOString().slice(0, 16);
};

export const localDateTimeInputToUtcIso = (
  value: string,
  timeZone?: string,
): string | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const normalized = trimmed.replace(" ", "T");
  const parsedParts = parseDateTimeInputParts(normalized);
  if (!parsedParts) {
    return null;
  }

  if (DATE_TIME_OFFSET_SUFFIX_PATTERN.test(normalized)) {
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) {
      return null;
    }
    return date.toISOString();
  }

  const resolved = normalizeTimeZone(timeZone) ?? resolveUserTimeZone();
  const utcDate = resolveLocalDateTimeToUtcDate(parsedParts, resolved);
  if (!utcDate) {
    return null;
  }
  return utcDate.toISOString();
};
