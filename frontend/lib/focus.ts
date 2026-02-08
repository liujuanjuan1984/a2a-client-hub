export function blurActiveElement() {
  if (typeof document === "undefined") return;
  const active = document.activeElement as HTMLElement | null;
  active?.blur?.();
}
