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
  const allowNextNavigationRef = useRef(false);

  const allowNextNavigation = useCallback(() => {
    allowNextNavigationRef.current = true;
  }, []);

  useEffect(() => {
    // Disable gestures while dirty to avoid iOS swipe-down losing changes without intent.
    navigation.setOptions({ gestureEnabled: !dirty });
  }, [navigation, dirty]);

  useEffect(() => {
    if (!dirty) {
      setPendingAction(null);
      allowNextNavigationRef.current = false;
    }
  }, [dirty]);

  usePreventRemove(dirty && pendingAction == null, ({ data }) => {
    if (allowNextNavigationRef.current) {
      allowNextNavigationRef.current = false;
      setPendingAction(data.action);
      return;
    }

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
  }, [navigation, pendingAction]);

  return { allowNextNavigation };
}
