import { apiRequest } from "@/lib/api/client";
import {
  parsePaginatedListResponse,
  resolveNextPageWithFallback,
} from "@/lib/api/pagination";
import {
  listScheduledJobExecutionsPage,
  listScheduledJobsPage,
} from "@/lib/api/scheduledJobs";
import { listSessionTimelinePage, listSessionsPage } from "@/lib/api/sessions";

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

  it("passes agent_id filter in sessions query body", async () => {
    mockedApiRequest.mockResolvedValueOnce({
      items: [],
      pagination: { page: 1, pages: 1 },
    } as any);

    await listSessionsPage({
      page: 1,
      size: 20,
      agent_id: "agent-123",
    });

    expect(mockedApiRequest).toHaveBeenCalledWith("/me/conversations:query", {
      method: "POST",
      body: {
        page: 1,
        size: 20,
        agent_id: "agent-123",
      },
    });
  });

  it("queries timeline page with before cursor and limit", async () => {
    mockedApiRequest.mockResolvedValueOnce({
      items: [
        {
          id: "msg-2",
          role: "agent",
          created_at: "2026-02-24T00:00:01.000Z",
          status: "done",
          metadata: {},
          blocks: [],
        },
      ],
      pageInfo: {
        hasMoreBefore: true,
        nextBefore: "cursor-1",
      },
      meta: { conversationId: "conversation-1", source: "manual" },
    } as any);

    const result = await listSessionTimelinePage("conversation-1", {
      before: "cursor-0",
      limit: 8,
    });

    expect(result.pageInfo).toEqual({
      hasMoreBefore: true,
      nextBefore: "cursor-1",
    });
    expect(mockedApiRequest).toHaveBeenCalledWith(
      "/me/conversations/conversation-1/messages:query",
      {
        method: "POST",
        body: {
          before: "cursor-0",
          limit: 8,
        },
      },
    );
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
