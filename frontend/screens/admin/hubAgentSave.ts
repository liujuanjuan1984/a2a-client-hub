import { executeWithAdminAutoAllowlist } from "@/lib/agentCreateAllowlist";
import { createProxyAllowlistEntry } from "@/lib/api/adminProxyAllowlist";
import { confirmAction } from "@/lib/confirm";
import { toast } from "@/lib/toast";

type HubAgentSaveMode = "create" | "update";

type SaveHubAgentWithAutoAllowlistOptions<T> = {
  mode: HubAgentSaveMode;
  isAdmin: boolean;
  cardUrl: string;
  run: () => Promise<T>;
  onCancel?: () => Promise<void> | void;
  onSuccess: (value: T) => Promise<void> | void;
};

const getConfirmMessage = (mode: HubAgentSaveMode, host: string) =>
  mode === "create"
    ? `The card URL host "${host}" is not in the proxy allowlist. Add it automatically and continue creating the agent?`
    : `The card URL host "${host}" is not in the proxy allowlist. Add it automatically and continue saving the shared agent?`;

const getCancelLabel = (mode: HubAgentSaveMode) =>
  mode === "create" ? "Exit Create" : "Keep Editing";

const getErrorTitle = (mode: HubAgentSaveMode) =>
  mode === "create" ? "Create failed" : "Save failed";

const getErrorFallback = (mode: HubAgentSaveMode) =>
  mode === "create" ? "Create failed." : "Save failed.";

export const saveHubAgentWithAutoAllowlist = async <T>({
  mode,
  isAdmin,
  cardUrl,
  run,
  onCancel,
  onSuccess,
}: SaveHubAgentWithAutoAllowlistOptions<T>): Promise<boolean> => {
  try {
    const result = await executeWithAdminAutoAllowlist({
      isAdmin,
      cardUrl,
      run,
      confirmAddHost: (host) =>
        confirmAction({
          title: "Host not allowlisted",
          message: getConfirmMessage(mode, host),
          confirmLabel: "Add and Continue",
          cancelLabel: getCancelLabel(mode),
        }),
      addHostToAllowlist: async (host) => {
        await createProxyAllowlistEntry({ host_pattern: host });
      },
      onCancel: onCancel ?? (() => undefined),
    });

    if (result.status === "cancelled") {
      return false;
    }

    await onSuccess(result.value);

    if (mode === "create") {
      const createdName =
        result.value &&
        typeof result.value === "object" &&
        "name" in result.value &&
        typeof result.value.name === "string"
          ? result.value.name
          : undefined;
      toast.success("Shared agent created", createdName);
    } else {
      toast.success("Saved", "Shared agent updated.");
    }

    return true;
  } catch (error) {
    const message =
      error instanceof Error ? error.message : getErrorFallback(mode);
    toast.error(getErrorTitle(mode), message);
    return false;
  }
};
