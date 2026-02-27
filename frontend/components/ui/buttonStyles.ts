export type ButtonVariant =
  | "primary"
  | "outline"
  | "ghost"
  | "danger"
  | "secondary"
  | "neo";
export type ButtonSize = "xs" | "sm" | "md" | "lg";

export const buttonVariants: Record<ButtonVariant, string> = {
  neo: "bg-yellow-500/75 active:bg-yellow-500/90",
  primary: "bg-yellow-500/75 active:bg-yellow-500/90",
  secondary: "bg-slate-800/35 border border-white/20 active:bg-slate-800/80",
  outline: "border border-white/10 active:bg-white/5",
  ghost: "active:bg-white/5",
  danger: "bg-red-500/10 border border-red-500/20 active:bg-red-500/20",
};

export const buttonIconColors: Record<ButtonVariant, string> = {
  neo: "#000000cc",
  primary: "#000000cc",
  secondary: "#94a3b8",
  outline: "#64748b",
  ghost: "#475569",
  danger: "#f87171cc",
};
