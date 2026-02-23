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

const formatterByTimeZone = new Map<string, Intl.DateTimeFormat>();

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

const toYmdHm = (date: Date, timeZone: string): string => {
  const parts = getFormatter(timeZone).formatToParts(date);
  const values = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );

  const year = values.year;
  const month = values.month;
  const day = values.day;
  const hour = values.hour;
  const minute = values.minute;

  if (!year || !month || !day || !hour || !minute) {
    return date.toISOString().slice(0, 16).replace("T", " ");
  }

  return `${year}-${month}-${day} ${hour}:${minute}`;
};

const DATE_TIME_INPUT_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?$/;

const hasValidDateTimeFields = (value: string): boolean => {
  const match = value.match(DATE_TIME_INPUT_PATTERN);
  if (!match) return false;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6] ?? "0");

  if (
    Number.isNaN(year) ||
    Number.isNaN(month) ||
    Number.isNaN(day) ||
    Number.isNaN(hour) ||
    Number.isNaN(minute) ||
    Number.isNaN(second)
  ) {
    return false;
  }

  if (month < 1 || month > 12) return false;
  if (day < 1 || day > 31) return false;
  if (hour < 0 || hour > 23) return false;
  if (minute < 0 || minute > 59) return false;
  if (second < 0 || second > 59) return false;

  const localCandidate = new Date(
    year,
    month - 1,
    day,
    hour,
    minute,
    second,
    0,
  );
  return (
    localCandidate.getFullYear() === year &&
    localCandidate.getMonth() === month - 1 &&
    localCandidate.getDate() === day &&
    localCandidate.getHours() === hour &&
    localCandidate.getMinutes() === minute &&
    localCandidate.getSeconds() === second
  );
};

export const formatLocalDateTime = (value?: string | null): string => {
  if (!value) return DATE_TIME_PLACEHOLDER;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return toYmdHm(date, resolveUserTimeZone());
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

export const localDateTimeInputToUtcIso = (value: string): string | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const normalized = trimmed.replace(" ", "T");
  if (!hasValidDateTimeFields(normalized)) return null;

  return normalized;
};
