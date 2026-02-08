import { create } from "zustand";

type ConfirmOptions = {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  isDestructive?: boolean;
};

type ConfirmRequest = Required<ConfirmOptions> & {
  id: number;
};

type ConfirmState = {
  request: ConfirmRequest | null;
  open: (options: ConfirmOptions) => Promise<boolean>;
  respond: (value: boolean) => void;
};

let nextRequestId = 1;
const resolversById = new Map<number, ((value: boolean) => void)[]>();

const resolveRequest = (id: number, value: boolean) => {
  const resolvers = resolversById.get(id) ?? [];
  resolversById.delete(id);
  resolvers.forEach((resolve) => resolve(value));
};

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  request: null,
  open: async (options) => {
    const existing = get().request;
    if (existing) {
      return new Promise<boolean>((resolve) => {
        const list = resolversById.get(existing.id) ?? [];
        list.push(resolve);
        resolversById.set(existing.id, list);
      });
    }

    const id = nextRequestId++;
    const request: ConfirmRequest = {
      id,
      title: options.title,
      message: options.message,
      confirmLabel: options.confirmLabel ?? "Confirm",
      cancelLabel: options.cancelLabel ?? "Cancel",
      isDestructive: options.isDestructive ?? false,
    };

    set({ request });

    return new Promise<boolean>((resolve) => {
      resolversById.set(id, [resolve]);
    });
  },
  respond: (value) => {
    const request = get().request;
    if (!request) return;
    set({ request: null });
    resolveRequest(request.id, value);
  },
}));
