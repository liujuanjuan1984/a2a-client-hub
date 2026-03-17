import {
  createWithAdminAutoAllowlist,
  extractCardUrlHost,
  isAllowlistEntryAlreadyExistsError,
  isCardUrlHostNotAllowedError,
} from "@/lib/agentCreateAllowlist";

const createApiError = (message: string, status: number, errorCode?: string) =>
  Object.assign(new Error(message), { status, errorCode });

describe("agentCreateAllowlist", () => {
  it("extracts a normalized host from card url", () => {
    expect(
      extractCardUrlHost(" https://Example.COM/.well-known/agent.json "),
    ).toBe("example.com");
  });

  it("recognizes allowlist rejection errors", () => {
    expect(
      isCardUrlHostNotAllowedError(
        createApiError(
          "Card URL host is not allowed [card_url_host_not_allowed]",
          403,
          "card_url_host_not_allowed",
        ),
      ),
    ).toBe(true);
    expect(
      isCardUrlHostNotAllowedError(
        createApiError("Card URL host is not allowed", 403),
      ),
    ).toBe(false);
  });

  it("recognizes duplicate allowlist entry errors", () => {
    expect(
      isAllowlistEntryAlreadyExistsError(
        createApiError("Host pattern 'example.com' already exists", 400),
      ),
    ).toBe(true);
  });

  it("retries create after admin confirms auto allowlist add", async () => {
    const create = jest
      .fn<Promise<{ id: string }>, []>()
      .mockRejectedValueOnce(
        createApiError(
          "Card URL host is not allowed [card_url_host_not_allowed]",
          403,
          "card_url_host_not_allowed",
        ),
      )
      .mockResolvedValueOnce({ id: "agent-1" });
    const confirmAddHost = jest.fn().mockResolvedValue(true);
    const addHostToAllowlist = jest.fn().mockResolvedValue(undefined);
    const onCancelCreate = jest.fn();

    const result = await createWithAdminAutoAllowlist({
      isAdmin: true,
      cardUrl: "https://example.com/agent.json",
      create,
      confirmAddHost,
      addHostToAllowlist,
      onCancelCreate,
    });

    expect(result).toEqual({ status: "created", value: { id: "agent-1" } });
    expect(confirmAddHost).toHaveBeenCalledWith("example.com");
    expect(addHostToAllowlist).toHaveBeenCalledWith("example.com");
    expect(create).toHaveBeenCalledTimes(2);
    expect(onCancelCreate).not.toHaveBeenCalled();
  });

  it("continues create when allowlist entry already exists", async () => {
    const create = jest
      .fn<Promise<{ id: string }>, []>()
      .mockRejectedValueOnce(
        createApiError(
          "Card URL host is not allowed [card_url_host_not_allowed]",
          403,
          "card_url_host_not_allowed",
        ),
      )
      .mockResolvedValueOnce({ id: "agent-2" });
    const confirmAddHost = jest.fn().mockResolvedValue(true);
    const addHostToAllowlist = jest
      .fn()
      .mockRejectedValue(
        createApiError("Host pattern 'example.com' already exists", 400),
      );

    const result = await createWithAdminAutoAllowlist({
      isAdmin: true,
      cardUrl: "https://example.com/agent.json",
      create,
      confirmAddHost,
      addHostToAllowlist,
      onCancelCreate: jest.fn(),
    });

    expect(result).toEqual({ status: "created", value: { id: "agent-2" } });
    expect(create).toHaveBeenCalledTimes(2);
  });

  it("cancels creation when admin declines auto allowlist add", async () => {
    const create = jest
      .fn<Promise<{ id: string }>, []>()
      .mockRejectedValue(
        createApiError(
          "Card URL host is not allowed [card_url_host_not_allowed]",
          403,
          "card_url_host_not_allowed",
        ),
      );
    const confirmAddHost = jest.fn().mockResolvedValue(false);
    const addHostToAllowlist = jest.fn();
    const onCancelCreate = jest.fn();

    const result = await createWithAdminAutoAllowlist({
      isAdmin: true,
      cardUrl: "https://example.com/agent.json",
      create,
      confirmAddHost,
      addHostToAllowlist,
      onCancelCreate,
    });

    expect(result).toEqual({ status: "cancelled" });
    expect(addHostToAllowlist).not.toHaveBeenCalled();
    expect(onCancelCreate).toHaveBeenCalledTimes(1);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("does not intercept allowlist errors for non-admin users", async () => {
    const error = createApiError(
      "Card URL host is not allowed [card_url_host_not_allowed]",
      403,
      "card_url_host_not_allowed",
    );

    await expect(
      createWithAdminAutoAllowlist({
        isAdmin: false,
        cardUrl: "https://example.com/agent.json",
        create: jest.fn().mockRejectedValue(error),
        confirmAddHost: jest.fn(),
        addHostToAllowlist: jest.fn(),
        onCancelCreate: jest.fn(),
      }),
    ).rejects.toBe(error);
  });
});
