import {
  DEFAULT_RUNTIME_STATUS_CONTRACT,
  type RuntimeStatusContract,
} from "@/lib/api/chat-utils";
import {
  listSessionMessagesPage,
  type SessionMessageItem,
} from "@/lib/api/sessions";
import {
  buildPendingInterruptState,
  createAgentSession,
  getPendingInterruptQueue,
} from "@/lib/chat-utils";
import {
  addConversationMessage,
  clearAllConversationMessages,
  getConversationMessages,
} from "@/lib/chatHistoryCache";
import { chatConnectionService } from "@/services/chatConnectionService";
import { queryClient } from "@/services/queryClient";
import {
  executeChatRuntime,
  type ChatRuntimeSetState,
  type ChatRuntimeState,
} from "@/store/chatRuntime";

jest.mock("@/lib/storage/mmkv", () =>
  require("@/test-utils/mockMmkv").createMockMmkvModule(),
);

jest.mock("@/services/chatConnectionService", () => ({
  chatConnectionService: {
    isWsHealthy: jest.fn(() => true),
    isSseHealthy: jest.fn(() => false),
    tryWebSocketTransport: jest.fn(async () => false),
    trySseTransport: jest.fn(async () => false),
  },
}));

jest.mock("@/lib/api/sessions", () => ({
  listSessionMessagesPage: jest.fn(),
}));

jest.mock("@/lib/api/a2aAgents", () => ({
  invokeAgent: jest.fn(async () => ({ success: true, content: "" })),
}));

jest.mock("@/lib/api/hubA2aAgentsUser", () => ({
  invokeHubAgent: jest.fn(async () => ({ success: true, content: "" })),
}));

const mockedListSessionMessagesPage =
  listSessionMessagesPage as jest.MockedFunction<
    typeof listSessionMessagesPage
  >;
const mockedChatConnectionService = chatConnectionService as jest.Mocked<
  typeof chatConnectionService
>;
const { invokeAgent } = require("@/lib/api/a2aAgents") as {
  invokeAgent: jest.Mock;
};
const { invokeHubAgent } = require("@/lib/api/hubA2aAgentsUser") as {
  invokeHubAgent: jest.Mock;
};
const { ApiRequestError } = require("@/lib/api/client") as {
  ApiRequestError: new (
    message: string,
    status: number,
    options?: {
      errorCode?: string | null;
      upstreamError?: Record<string, unknown> | null;
    },
  ) => Error;
};

const flushPromises = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
};

const createDeferred = <T>() => {
  let resolve: ((value: T) => void) | null = null;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return {
    promise,
    resolve: (value: T) => {
      if (resolve) {
        resolve(value);
      }
    },
  };
};

let consoleWarnSpy: jest.SpyInstance;
let consoleInfoSpy: jest.SpyInstance;

beforeAll(() => {
  consoleWarnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
  consoleInfoSpy = jest.spyOn(console, "info").mockImplementation(() => {});
});

afterAll(() => {
  consoleWarnSpy.mockRestore();
  consoleInfoSpy.mockRestore();
});

export {
  ApiRequestError,
  DEFAULT_RUNTIME_STATUS_CONTRACT,
  addConversationMessage,
  buildPendingInterruptState,
  clearAllConversationMessages,
  createAgentSession,
  createDeferred,
  executeChatRuntime,
  flushPromises,
  getConversationMessages,
  getPendingInterruptQueue,
  invokeAgent,
  invokeHubAgent,
  mockedChatConnectionService,
  mockedListSessionMessagesPage,
  queryClient,
};

export type {
  ChatRuntimeSetState,
  ChatRuntimeState,
  RuntimeStatusContract,
  SessionMessageItem,
};
