import { FullscreenLoader } from "@/components/ui/FullscreenLoader";

export function RouteScreenFallback({
  message = "Loading page...",
}: {
  message?: string;
}) {
  return <FullscreenLoader message={message} />;
}
