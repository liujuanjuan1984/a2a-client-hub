import { QueryClient } from "@tanstack/react-query";

const isTestEnv = process.env.NODE_ENV === "test";
const testGcTime = isTestEnv ? Infinity : undefined;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      gcTime: testGcTime,
    },
    mutations: {
      gcTime: testGcTime,
    },
  },
});
