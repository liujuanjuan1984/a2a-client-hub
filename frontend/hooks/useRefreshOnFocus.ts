import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef } from "react";
import { AppState, type AppStateStatus } from "react-native";

export function useRefreshOnFocus<T>(refetch: () => Promise<T>) {
  const firstTimeRef = useRef(true);
  const isFocusedRef = useRef(false);

  useFocusEffect(
    useCallback(() => {
      isFocusedRef.current = true;
      if (firstTimeRef.current) {
        firstTimeRef.current = false;
      } else {
        refetch();
      }
      return () => {
        isFocusedRef.current = false;
      };
    }, [refetch]),
  );

  useEffect(() => {
    if (!AppState || typeof AppState.addEventListener !== "function") {
      return;
    }
    const subscription = AppState.addEventListener(
      "change",
      (status: AppStateStatus) => {
        if (status === "active" && isFocusedRef.current) {
          refetch();
        }
      },
    );
    return () => subscription?.remove?.();
  }, [refetch]);
}
