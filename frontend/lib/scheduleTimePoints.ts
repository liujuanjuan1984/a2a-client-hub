import {
  type DailyTimePoint,
  type IntervalTimePoint,
  type MonthlyTimePoint,
  type ScheduleCycleType,
  type ScheduleTimePoint,
  type SequentialTimePoint,
  type WeeklyTimePoint,
} from "@/lib/api/scheduledJobs";

type ScheduleTimePointByCycle = {
  daily: DailyTimePoint;
  weekly: WeeklyTimePoint;
  monthly: MonthlyTimePoint;
  interval: IntervalTimePoint;
  sequential: SequentialTimePoint;
};

type ScheduleCycleTimePoint<T extends ScheduleCycleType> =
  ScheduleTimePointByCycle[T];

const DEFAULT_TIME = "07:00";
const DEFAULT_WEEKDAY = 1;
const DEFAULT_MONTH_DAY = 1;
const DEFAULT_MINUTES = 10;

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

export const normalizeScheduleMinutes = (value: number) =>
  Math.max(5, Math.min(1440, value));

export const normalizeTimePoint = <T extends ScheduleCycleType>(
  cycleType: T,
  timePoint: unknown,
): ScheduleCycleTimePoint<T> => {
  const current = asRecord(timePoint);

  if (cycleType === "daily") {
    const time = current.time;
    return {
      time: typeof time === "string" ? time : DEFAULT_TIME,
    } as ScheduleCycleTimePoint<T>;
  }

  if (cycleType === "weekly") {
    const weekday = current.weekday;
    const time = current.time;
    return {
      weekday: typeof weekday === "number" ? weekday : DEFAULT_WEEKDAY,
      time: typeof time === "string" ? time : DEFAULT_TIME,
    } as ScheduleCycleTimePoint<T>;
  }

  if (cycleType === "monthly") {
    const day = current.day;
    const time = current.time;
    return {
      day:
        typeof day === "number"
          ? Math.max(1, Math.min(31, day))
          : DEFAULT_MONTH_DAY,
      time: typeof time === "string" ? time : DEFAULT_TIME,
    } as ScheduleCycleTimePoint<T>;
  }

  if (cycleType === "interval") {
    const minutes = current.minutes;
    const startAtLocal = current.start_at_local;
    return {
      minutes:
        typeof minutes === "number" && Number.isFinite(minutes)
          ? normalizeScheduleMinutes(minutes)
          : DEFAULT_MINUTES,
      ...(typeof startAtLocal === "string" && startAtLocal.trim()
        ? { start_at_local: startAtLocal.trim() }
        : {}),
    } as ScheduleCycleTimePoint<T>;
  }

  const minutes = current.minutes;
  return {
    minutes:
      typeof minutes === "number" && Number.isFinite(minutes)
        ? normalizeScheduleMinutes(minutes)
        : DEFAULT_MINUTES,
  } as ScheduleCycleTimePoint<T>;
};

export const patchTimePoint = <T extends ScheduleCycleType>(
  cycleType: T,
  current: unknown,
  patch: Partial<ScheduleCycleTimePoint<T>>,
): ScheduleCycleTimePoint<T> => ({
  ...normalizeTimePoint(cycleType, current),
  ...patch,
});

export const getIntervalStartAtLocal = (timePoint: unknown) =>
  normalizeTimePoint("interval", timePoint).start_at_local ?? "";

export const normalizeScheduledJobTimePoint = (
  cycleType: ScheduleCycleType,
  timePoint: unknown,
): ScheduleTimePoint => normalizeTimePoint(cycleType, timePoint);
