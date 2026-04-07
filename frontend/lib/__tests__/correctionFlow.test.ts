import { executeWithCorrection } from "@/lib/correctionFlow";

const createError = (message: string) => new Error(message);

describe("executeWithCorrection", () => {
  it("retries the original action after confirmation and correction", async () => {
    const run = jest
      .fn<Promise<{ ok: boolean }>, []>()
      .mockRejectedValueOnce(createError("needs-fix"))
      .mockResolvedValueOnce({ ok: true });
    const confirm = jest.fn().mockResolvedValue(true);
    const apply = jest.fn().mockResolvedValue(undefined);

    const result = await executeWithCorrection({
      run,
      onCancel: jest.fn(),
      resolveCorrection: (error) => {
        if (!(error instanceof Error) || error.message !== "needs-fix") {
          return null;
        }
        return {
          context: { code: "needs-fix" },
          confirm,
          apply,
        };
      },
    });

    expect(result).toEqual({ status: "completed", value: { ok: true } });
    expect(confirm).toHaveBeenCalledWith({ code: "needs-fix" });
    expect(apply).toHaveBeenCalledWith({ code: "needs-fix" });
    expect(run).toHaveBeenCalledTimes(2);
  });

  it("returns cancelled when the user declines the correction", async () => {
    const run = jest
      .fn<Promise<{ ok: boolean }>, []>()
      .mockRejectedValue(createError("needs-fix"));
    const onCancel = jest.fn();

    const result = await executeWithCorrection({
      run,
      onCancel,
      resolveCorrection: () => ({
        context: "needs-fix",
        confirm: jest.fn().mockResolvedValue(false),
        apply: jest.fn(),
      }),
    });

    expect(result).toEqual({ status: "cancelled" });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("allows the correction step to ignore known apply errors", async () => {
    const run = jest
      .fn<Promise<{ ok: boolean }>, []>()
      .mockRejectedValueOnce(createError("needs-fix"))
      .mockResolvedValueOnce({ ok: true });

    const result = await executeWithCorrection({
      run,
      onCancel: jest.fn(),
      resolveCorrection: () => ({
        context: "needs-fix",
        confirm: jest.fn().mockResolvedValue(true),
        apply: jest.fn().mockRejectedValue(createError("already-fixed")),
        shouldIgnoreApplyError: (error) =>
          error instanceof Error && error.message === "already-fixed",
      }),
    });

    expect(result).toEqual({ status: "completed", value: { ok: true } });
    expect(run).toHaveBeenCalledTimes(2);
  });

  it("rethrows the original error when no correction applies", async () => {
    const error = createError("no-fix");

    await expect(
      executeWithCorrection({
        run: jest.fn().mockRejectedValue(error),
        onCancel: jest.fn(),
        resolveCorrection: () => null,
      }),
    ).rejects.toBe(error);
  });
});
