import { asRecord } from "./chatUtilsShared";

export type StreamEnvelope = {
  version: "v1";
  streamBlock?: Record<string, unknown> | null;
  runtimeStatus?: Record<string, unknown> | null;
  sessionMeta?: Record<string, unknown> | null;
};

export const extractStreamEnvelope = (
  data: Record<string, unknown>,
): StreamEnvelope | null => {
  const envelope = asRecord(data);
  if (!envelope) {
    return null;
  }
  const version = envelope.version;
  if (version !== "v1") {
    return null;
  }
  return {
    version,
    streamBlock: asRecord(envelope.streamBlock),
    runtimeStatus: asRecord(envelope.runtimeStatus),
    sessionMeta: asRecord(envelope.sessionMeta),
  };
};
