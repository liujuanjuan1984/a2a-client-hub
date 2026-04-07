export type CorrectionExecutionResult<T> =
  | { status: "completed"; value: T }
  | { status: "cancelled" };

export type CorrectionPlan<TContext> = {
  context: TContext;
  confirm: (context: TContext) => Promise<boolean>;
  apply: (context: TContext) => Promise<void>;
  shouldIgnoreApplyError?: (error: unknown, context: TContext) => boolean;
};

type ExecuteWithCorrectionOptions<T, TContext> = {
  run: () => Promise<T>;
  resolveCorrection:
    | ((error: unknown) => CorrectionPlan<TContext> | null)
    | ((error: unknown) => Promise<CorrectionPlan<TContext> | null>);
  onCancel: () => void | Promise<void>;
};

export const executeWithCorrection = async <T, TContext>({
  run,
  resolveCorrection,
  onCancel,
}: ExecuteWithCorrectionOptions<T, TContext>): Promise<
  CorrectionExecutionResult<T>
> => {
  try {
    return { status: "completed", value: await run() };
  } catch (error) {
    const correction = await resolveCorrection(error);
    if (!correction) {
      throw error;
    }

    const confirmed = await correction.confirm(correction.context);
    if (!confirmed) {
      await onCancel();
      return { status: "cancelled" };
    }

    try {
      await correction.apply(correction.context);
    } catch (applyError) {
      if (
        !correction.shouldIgnoreApplyError?.(applyError, correction.context)
      ) {
        throw applyError;
      }
    }

    return { status: "completed", value: await run() };
  }
};
