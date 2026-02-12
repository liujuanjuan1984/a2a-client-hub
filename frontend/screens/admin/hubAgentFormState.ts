import { useCallback, useMemo, useState } from "react";

import type {
  HubA2AAgentAdminCreate,
  HubA2AAgentAdminResponse,
  HubA2AAuthType,
  HubA2AAvailabilityPolicy,
} from "@/lib/api/hubA2aAgentsAdmin";
import { generateId } from "@/lib/id";
import {
  type HeaderRow,
  headerRowsToRecord,
  parseTags,
  recordToHeaderRows,
  validateHttpUrl,
} from "@/screens/admin/hubAgentFormUtils";

export type HubAgentFormErrors = {
  name?: string;
  cardUrl?: string;
};

export type HubAgentFormValues = {
  name: string;
  cardUrl: string;
  enabled: boolean;
  availabilityPolicy: HubA2AAvailabilityPolicy;
  authType: HubA2AAuthType;
  authHeader: string;
  authScheme: string;
  token: string;
  tagsText: string;
  extraHeaders: HeaderRow[];
};

export const createDefaultHubAgentFormValues = (): HubAgentFormValues => ({
  name: "",
  cardUrl: "",
  enabled: true,
  availabilityPolicy: "public",
  authType: "none",
  authHeader: "Authorization",
  authScheme: "Bearer",
  token: "",
  tagsText: "",
  extraHeaders: recordToHeaderRows({}),
});

export const createHubAgentFormValuesFromRecord = (
  record: HubA2AAgentAdminResponse,
): HubAgentFormValues => ({
  name: record.name ?? "",
  cardUrl: record.card_url ?? "",
  enabled: Boolean(record.enabled),
  availabilityPolicy: record.availability_policy,
  authType: record.auth_type,
  authHeader: record.auth_header ?? "Authorization",
  authScheme: record.auth_scheme ?? "Bearer",
  token: "",
  tagsText: (record.tags ?? []).join(", "),
  extraHeaders: recordToHeaderRows(record.extra_headers ?? {}),
});

export type HubAgentComparablePayload = {
  name: string;
  card_url: string;
  enabled: boolean;
  availability_policy: HubA2AAvailabilityPolicy;
  auth_type: HubA2AAuthType;
  auth_header: string | null;
  auth_scheme: string | null;
  tags: string[];
  extra_headers: Record<string, string>;
};

export const buildHubAgentComparablePayload = (
  values: HubAgentFormValues,
): HubAgentComparablePayload => ({
  name: values.name.trim(),
  card_url: values.cardUrl.trim(),
  enabled: values.enabled,
  availability_policy: values.availabilityPolicy,
  auth_type: values.authType,
  auth_header: values.authType === "bearer" ? values.authHeader.trim() : null,
  auth_scheme: values.authType === "bearer" ? values.authScheme.trim() : null,
  tags: parseTags(values.tagsText),
  extra_headers: headerRowsToRecord(values.extraHeaders),
});

export const buildHubAgentComparablePayloadFromRecord = (
  record: HubA2AAgentAdminResponse,
): HubAgentComparablePayload => ({
  name: record.name,
  card_url: record.card_url,
  enabled: record.enabled,
  availability_policy: record.availability_policy,
  auth_type: record.auth_type,
  auth_header: record.auth_header ?? null,
  auth_scheme: record.auth_scheme ?? null,
  tags: record.tags ?? [],
  extra_headers: record.extra_headers ?? {},
});

export const buildHubAgentPayload = (
  values: HubAgentFormValues,
): HubA2AAgentAdminCreate => {
  const payload: HubA2AAgentAdminCreate = {
    name: values.name.trim(),
    card_url: values.cardUrl.trim(),
    availability_policy: values.availabilityPolicy,
    auth_type: values.authType,
    auth_header: values.authType === "bearer" ? values.authHeader.trim() : null,
    auth_scheme: values.authType === "bearer" ? values.authScheme.trim() : null,
    enabled: values.enabled,
    tags: parseTags(values.tagsText),
    extra_headers: headerRowsToRecord(values.extraHeaders),
  };
  const trimmedToken = values.token.trim();
  if (trimmedToken) {
    payload.token = trimmedToken;
  }
  return payload;
};

const hasDraftValue = (values: HubAgentFormValues): boolean =>
  Boolean(values.name.trim()) ||
  Boolean(values.cardUrl.trim()) ||
  values.tagsText.trim().length > 0 ||
  values.token.trim().length > 0 ||
  values.extraHeaders.some((row) => row.key.trim() || row.value.trim());

export const useHubAgentFormState = () => {
  const [values, setValues] = useState<HubAgentFormValues>(
    createDefaultHubAgentFormValues(),
  );
  const [errors, setErrors] = useState<HubAgentFormErrors>({});

  const setName = useCallback((value: string) => {
    setValues((prev) => ({ ...prev, name: value }));
  }, []);
  const setCardUrl = useCallback((value: string) => {
    setValues((prev) => ({ ...prev, cardUrl: value }));
  }, []);
  const setEnabled = useCallback((value: boolean) => {
    setValues((prev) => ({ ...prev, enabled: value }));
  }, []);
  const setAvailabilityPolicy = useCallback(
    (value: HubA2AAvailabilityPolicy) => {
      setValues((prev) => ({ ...prev, availabilityPolicy: value }));
    },
    [],
  );
  const setAuthType = useCallback((value: HubA2AAuthType) => {
    setValues((prev) => ({ ...prev, authType: value }));
  }, []);
  const setAuthHeader = useCallback((value: string) => {
    setValues((prev) => ({ ...prev, authHeader: value }));
  }, []);
  const setAuthScheme = useCallback((value: string) => {
    setValues((prev) => ({ ...prev, authScheme: value }));
  }, []);
  const setToken = useCallback((value: string) => {
    setValues((prev) => ({ ...prev, token: value }));
  }, []);
  const setTagsText = useCallback((value: string) => {
    setValues((prev) => ({ ...prev, tagsText: value }));
  }, []);

  const setHeaderRow = useCallback(
    (id: string, field: "key" | "value", value: string) => {
      setValues((prev) => ({
        ...prev,
        extraHeaders: prev.extraHeaders.map((row) =>
          row.id === id ? { ...row, [field]: value } : row,
        ),
      }));
    },
    [],
  );

  const removeHeaderRow = useCallback((id: string) => {
    setValues((prev) => {
      const next = prev.extraHeaders.filter((row) => row.id !== id);
      return {
        ...prev,
        extraHeaders: next.length ? next : recordToHeaderRows({}),
      };
    });
  }, []);

  const addHeaderRow = useCallback(() => {
    setValues((prev) => ({
      ...prev,
      extraHeaders: [
        ...prev.extraHeaders,
        { id: generateId(), key: "", value: "" },
      ],
    }));
  }, []);

  const hydrateFromRecord = useCallback((record: HubA2AAgentAdminResponse) => {
    setValues(createHubAgentFormValuesFromRecord(record));
    setErrors({});
  }, []);

  const validate = useCallback(() => {
    const nextErrors: HubAgentFormErrors = {};
    if (!values.name.trim()) nextErrors.name = "Name is required.";
    if (!values.cardUrl.trim())
      nextErrors.cardUrl = "Agent Card URL is required.";
    if (values.cardUrl.trim() && !validateHttpUrl(values.cardUrl.trim())) {
      nextErrors.cardUrl = "Please enter a valid http(s) URL.";
    }
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }, [values.cardUrl, values.name]);

  const canSave = useMemo(
    () => Boolean(values.name.trim()) && Boolean(values.cardUrl.trim()),
    [values.cardUrl, values.name],
  );
  const hasDraftInput = useMemo(() => hasDraftValue(values), [values]);
  const comparablePayload = useMemo(
    () => buildHubAgentComparablePayload(values),
    [values],
  );

  const buildPayload = useCallback(
    () => buildHubAgentPayload(values),
    [values],
  );

  return {
    values,
    errors,
    canSave,
    hasDraftInput,
    comparablePayload,
    setName,
    setCardUrl,
    setEnabled,
    setAvailabilityPolicy,
    setAuthType,
    setAuthHeader,
    setAuthScheme,
    setToken,
    setTagsText,
    setHeaderRow,
    removeHeaderRow,
    addHeaderRow,
    hydrateFromRecord,
    validate,
    buildPayload,
  };
};
