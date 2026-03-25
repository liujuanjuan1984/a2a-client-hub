const ALREADY_EXISTS = "already exists";

type ApiLikeError = {
  status?: unknown;
  message?: unknown;
  errorCode?: unknown;
};

const asApiLikeError = (error: unknown): ApiLikeError | null => {
  if (!error || typeof error !== "object") {
    return null;
  }
  return error as ApiLikeError;
};

export const extractCardUrlHost = (cardUrl: string): string | null => {
  try {
    const host = new URL(cardUrl.trim()).host.trim().toLowerCase();
    return host || null;
  } catch {
    return null;
  }
};

export const isCardUrlHostNotAllowedError = (error: unknown): boolean => {
  const apiError = asApiLikeError(error);
  if (!apiError || apiError.status !== 403) {
    return false;
  }
  return apiError.errorCode === "card_url_host_not_allowed";
};

export const isAllowlistEntryAlreadyExistsError = (error: unknown): boolean => {
  const apiError = asApiLikeError(error);
  if (!apiError || apiError.status !== 400) {
    return false;
  }
  return (
    typeof apiError.message === "string" &&
    apiError.message.toLowerCase().includes(ALREADY_EXISTS)
  );
};

type AutoAllowlistActionOptions<T> = {
  isAdmin: boolean;
  cardUrl: string;
  run: () => Promise<T>;
  confirmAddHost: (host: string) => Promise<boolean>;
  addHostToAllowlist: (host: string) => Promise<void>;
  onCancel: () => void | Promise<void>;
};

type AutoAllowlistActionResult<T> =
  | { status: "created"; value: T }
  | { status: "cancelled" };

export const executeWithAdminAutoAllowlist = async <T>({
  isAdmin,
  cardUrl,
  run,
  confirmAddHost,
  addHostToAllowlist,
  onCancel,
}: AutoAllowlistActionOptions<T>): Promise<AutoAllowlistActionResult<T>> => {
  try {
    return { status: "created", value: await run() };
  } catch (error) {
    if (!isAdmin || !isCardUrlHostNotAllowedError(error)) {
      throw error;
    }

    const host = extractCardUrlHost(cardUrl);
    if (!host) {
      throw error;
    }

    const confirmed = await confirmAddHost(host);
    if (!confirmed) {
      await onCancel();
      return { status: "cancelled" };
    }

    try {
      await addHostToAllowlist(host);
    } catch (allowlistError) {
      if (!isAllowlistEntryAlreadyExistsError(allowlistError)) {
        throw allowlistError;
      }
    }

    return { status: "created", value: await run() };
  }
};

export const createWithAdminAutoAllowlist = executeWithAdminAutoAllowlist;
