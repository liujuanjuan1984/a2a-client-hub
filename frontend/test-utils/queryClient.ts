import { QueryClient } from "@tanstack/react-query";

export const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
      },
      mutations: {
        retry: false,
        gcTime: Infinity,
      },
    },
  });

export const cleanupTestQueryClient = async (queryClient: QueryClient) => {
  await queryClient.cancelQueries();
  queryClient.clear();
};
