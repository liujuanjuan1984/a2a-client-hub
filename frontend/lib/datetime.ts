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
): string => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  const year = String(date.getFullYear());
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");

  return `${year}-${month}-${day}T${hour}:${minute}`;
};

export const localDateTimeInputToUtcIso = (value: string): string | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const normalized = trimmed.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return null;

  return date.toISOString();
};
