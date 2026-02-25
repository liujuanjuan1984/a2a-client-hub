import { apiRequest } from "@/lib/api/client";
import {
  parsePaginatedListResponse,
  resolveNextPageWithFallback,
} from "@/lib/api/pagination";
import {
  listScheduledJobExecutionsPage,
  listScheduledJobsPage,
} from "@/lib/api/scheduledJobs";
import { listSessionMessagesPage, listSessionsPage } from "@/lib/api/sessions";

jest.mock("@/lib/api/client", () => ({
  apiRequest: jest.fn(),
}));

const mockedApiRequest = apiRequest as jest.MockedFunction<typeof apiRequest>;

describe("pagination fallback helpers", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("uses explicit nextPage from parsed pagination first", () => {
    const parsed = parsePaginatedListResponse({
      items: [{ id: "a" }],
      pagination: { page: 1, next_page: 3, has_next: true },
    });

    const nextPage = resolveNextPageWithFallback({
      parsed,
      page: 1,
      size: 50,
    });

    expect(nextPage).toBe(3);
  });

  it("falls back to legacy pagination.pages", () => {
    const parsed = parsePaginatedListResponse({
      items: [{ id: "a" }],
      pagination: { pages: 4 },
    });

    const nextPage = resolveNextPageWithFallback({
      parsed,
      page: 2,
      size: 50,
    });

    expect(nextPage).toBe(3);
  });

  it("falls back to size heuristic when pagination metadata is absent", () => {
    const parsed = parsePaginatedListResponse({
      items: Array.from({ length: 2 }, (_, index) => ({ id: `item-${index}` })),
    });

    const nextPage = resolveNextPageWithFallback({
      parsed,
      page: 1,
      size: 2,
    });

    expect(nextPage).toBe(2);
  });
});

describe("API modules using shared pagination fallback", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("resolves sessions nextPage from legacy pages metadata", async () => {
    mockedApiRequest.mockResolvedValueOnce({
      items: [
        {
          conversationId: "conv-1",
          source: "manual",
          title: "Conversation 1",
        },
      ],
      pagination: { pages: 3 },
    } as any);

    const result = await listSessionsPage({ page: 1, size: 50 });

    expect(result.nextPage).toBe(2);
  });

  it("resolves session messages nextPage from size heuristic", async () => {
    mockedApiRequest.mockResolvedValueOnce({
      items: [
        {
          id: "msg-1",
          role: "user",
          content: "hello",
          created_at: "2026-02-24T00:00:00.000Z",
        },
        {
          id: "msg-2",
          role: "agent",
          created_at: "2026-02-24T00:00:01.000Z",
        },
      ],
    } as any);
    mockedApiRequest.mockResolvedValueOnce({
      items: [
        {
          messageId: "msg-2",
          role: "agent",
          blockCount: 1,
          hasBlocks: true,
          blocks: [
            {
              id: "msg-2:block-1",
              messageId: "msg-2",
              seq: 1,
              type: "text",
              content: "world",
              contentLength: 5,
              isFinished: true,
            },
          ],
        },
      ],
      meta: { conversationId: "conversation-1", mode: "full" },
    } as any);

    const result = await listSessionMessagesPage("conversation-1", {
      page: 1,
      size: 2,
    });

    expect(result.nextPage).toBe(2);
    expect(result.items[1]).toMatchObject({
      id: "msg-2",
      blocks: [expect.objectContaining({ id: "msg-2:block-1" })],
    });
  });

  it("resolves scheduled jobs nextPage from parsed pagination", async () => {
    mockedApiRequest.mockResolvedValueOnce({
      items: [
        {
          id: "job-1",
          name: "Job 1",
          agent_id: "agent-1",
          prompt: "Hello",
          cycle_type: "daily",
          time_point: { time: "07:00" },
          schedule_timezone: "UTC",
          enabled: true,
          conversation_policy: "new_each_run",
          created_at: "2026-02-24T00:00:00.000Z",
          updated_at: "2026-02-24T00:00:00.000Z",
        },
      ],
      pagination: { page: 1, next_page: 2, has_next: true },
    } as any);

    const result = await listScheduledJobsPage({ page: 1, size: 50 });

    expect(result.nextPage).toBe(2);
  });

  it("resolves scheduled job executions nextPage from size heuristic", async () => {
    mockedApiRequest.mockResolvedValueOnce({
      items: [
        {
          id: "exec-1",
          task_id: "job-1",
          status: "success",
          scheduled_for: "2026-02-24T00:00:00.000Z",
          started_at: "2026-02-24T00:00:01.000Z",
        },
      ],
    } as any);

    const result = await listScheduledJobExecutionsPage("job-1", {
      page: 1,
      size: 1,
    });

    expect(result.nextPage).toBe(2);
  });
});
