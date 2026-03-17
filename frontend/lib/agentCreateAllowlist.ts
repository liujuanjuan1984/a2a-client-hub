const CARD_URL_HOST_NOT_ALLOWED = "Card URL host is not allowed";
const ALREADY_EXISTS = "already exists";

type ApiLikeError = {
  status?: unknown;
  message?: unknown;
};

const asApiLikeError = (error: unknown): ApiLikeError | null => {
  if (!error || typeof error !== "object") {
    return null;
  }
  return error as ApiLikeError;
};

export const extractCardUrlHost = (cardUrl: string): string | null => {
  try {
    const host = new URL(cardUrl.trim()).hostname.trim().toLowerCase();
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
  return (
    typeof apiError.message === "string" &&
    apiError.message.includes(CARD_URL_HOST_NOT_ALLOWED)
  );
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

type AutoAllowlistCreateOptions<T> = {
  isAdmin: boolean;
  cardUrl: string;
  create: () => Promise<T>;
  confirmAddHost: (host: string) => Promise<boolean>;
  addHostToAllowlist: (host: string) => Promise<void>;
  onCancelCreate: () => void | Promise<void>;
};

type AutoAllowlistCreateResult<T> =
  | { status: "created"; value: T }
  | { status: "cancelled" };

export const createWithAdminAutoAllowlist = async <T>({
  isAdmin,
  cardUrl,
  create,
  confirmAddHost,
  addHostToAllowlist,
  onCancelCreate,
}: AutoAllowlistCreateOptions<T>): Promise<AutoAllowlistCreateResult<T>> => {
  try {
    return { status: "created", value: await create() };
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
      await onCancelCreate();
      return { status: "cancelled" };
    }

    try {
      await addHostToAllowlist(host);
    } catch (allowlistError) {
      if (!isAllowlistEntryAlreadyExistsError(allowlistError)) {
        throw allowlistError;
      }
    }

    return { status: "created", value: await create() };
  }
};
