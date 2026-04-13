export const createMockMmkvModule = () => ({
  buildPersistStorageName: (key: string) => key,
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
});
