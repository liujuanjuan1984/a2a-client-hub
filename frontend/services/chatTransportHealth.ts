import { Platform } from "react-native";

import {
  supportsStreaming,
  supportsWebSocket,
} from "@/services/chatTransportCommon";

type PreferredTransport = "ws" | "http_sse" | "http_json";
type FallbackChannel = "WS" | "SSE";

const fallbackLogThrottleMs = 15_000;
const fallbackLogTimestamps = new Map<string, number>();

const logFallback = (channel: FallbackChannel, reason: string) => {
  const key = `${channel}:${reason}`;
  const now = Date.now();
  const previous = fallbackLogTimestamps.get(key);
  if (previous && now - previous < fallbackLogThrottleMs) {
    return;
  }
  fallbackLogTimestamps.set(key, now);
  console.info(`[${channel} Fallback]`, {
    platform: Platform.OS,
    reason,
  });
};

export class ChatTransportHealth {
  private wsConsecutiveFailures = 0;
  private sseConsecutiveFailures = 0;
  private readonly failureThreshold = 2;

  getPreferredTransport(): PreferredTransport {
    if (this.isWsHealthy()) return "ws";
    if (this.isSseHealthy()) return "http_sse";
    return "http_json";
  }

  isWsHealthy(): boolean {
    return (
      supportsWebSocket && this.wsConsecutiveFailures < this.failureThreshold
    );
  }

  isSseHealthy(): boolean {
    return (
      supportsStreaming && this.sseConsecutiveFailures < this.failureThreshold
    );
  }

  recordWsSuccess(): void {
    this.wsConsecutiveFailures = 0;
  }

  recordWsFailure(error: unknown): void {
    this.wsConsecutiveFailures += 1;
    logFallback("WS", error instanceof Error ? error.message : String(error));
  }

  recordSseSuccess(): void {
    this.sseConsecutiveFailures = 0;
  }

  recordSseFailure(error: unknown): void {
    this.sseConsecutiveFailures += 1;
    logFallback("SSE", error instanceof Error ? error.message : String(error));
  }
}
