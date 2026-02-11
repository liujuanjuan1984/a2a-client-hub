import { usePreventRemove } from "@react-navigation/core";
import { useNavigation, type ParamListBase } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import type { NavigationAction } from "@react-navigation/routers";
import { useCallback, useEffect, useRef, useState } from "react";

import { confirmAction } from "@/lib/confirm";

type Options = {
  dirty: boolean;
  title?: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
};

const ALLOW_NEXT_NAVIGATION_WINDOW_MS = 2_000;

/**
 * Prevents accidental dismissal (back gesture / hardware back / modal swipe-down)
 * when the current screen has unsaved changes.
 */
export function usePreventRemoveWhenDirty({
  dirty,
  title = "Discard changes?",
  message = "You have unsaved changes. Discard them and leave?",
  confirmLabel = "Discard",
  cancelLabel = "Stay",
}: Options) {
  const navigation = useNavigation<NativeStackNavigationProp<ParamListBase>>();
  const [pendingAction, setPendingAction] = useState<NavigationAction | null>(
    null,
  );
  const allowNextNavigationUntilMsRef = useRef(0);

  const allowNextNavigation = useCallback(() => {
    allowNextNavigationUntilMsRef.current =
      Date.now() + ALLOW_NEXT_NAVIGATION_WINDOW_MS;
  }, []);

  useEffect(() => {
    // Disable gestures while dirty to avoid iOS swipe-down losing changes without intent.
    navigation.setOptions({ gestureEnabled: !dirty });
  }, [navigation, dirty]);

  useEffect(() => {
    if (!dirty) {
      setPendingAction(null);
      allowNextNavigationUntilMsRef.current = 0;
    }
  }, [dirty]);

  usePreventRemove(dirty && pendingAction == null, ({ data }) => {
    const now = Date.now();
    if (allowNextNavigationUntilMsRef.current > now) {
      allowNextNavigationUntilMsRef.current = 0;
      setPendingAction(data.action);
      return;
    }
    allowNextNavigationUntilMsRef.current = 0;

    confirmAction({
      title,
      message,
      confirmLabel,
      cancelLabel,
      isDestructive: true,
    }).then((shouldDiscard) => {
      if (!shouldDiscard) return;
      // Allow the next navigation action to proceed without looping the guard.
      setPendingAction(data.action);
    });
  });

  useEffect(() => {
    if (!pendingAction) return;
    navigation.dispatch(pendingAction);
    setPendingAction(null);
  }, [navigation, pendingAction]);

  return { allowNextNavigation };
}
