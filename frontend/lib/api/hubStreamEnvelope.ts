import { asRecord } from "./chatUtilsShared";

export type HubStreamEnvelope = {
  version: "v1";
  streamBlock?: Record<string, unknown> | null;
  runtimeStatus?: Record<string, unknown> | null;
  sessionMeta?: Record<string, unknown> | null;
};

export const extractHubStreamEnvelope = (
  data: Record<string, unknown>,
): HubStreamEnvelope | null => {
  const hub = asRecord(data.hub);
  if (!hub) {
    return null;
  }
  const version = hub.version;
  if (version !== "v1") {
    return null;
  }
  return {
    version,
    streamBlock: asRecord(hub.streamBlock),
    runtimeStatus: asRecord(hub.runtimeStatus),
    sessionMeta: asRecord(hub.sessionMeta),
  };
};
