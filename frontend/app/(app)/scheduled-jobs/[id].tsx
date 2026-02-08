import { useLocalSearchParams } from "expo-router";

import { ScheduledJobFormScreen } from "@/screens/ScheduledJobFormScreen";

export default function EditScheduledJobPage() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  return (
    <ScheduledJobFormScreen jobId={typeof id === "string" ? id : undefined} />
  );
}
