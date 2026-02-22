import { useLocalSearchParams } from "expo-router";

import { ScheduledJobFormScreen } from "@/screens/ScheduledJobFormScreen";
import { PageTitle } from "@/components/layout/PageTitle";

export default function EditScheduledJobPage() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  return (
    <>
      <PageTitle title="Edit Job" />
      <ScheduledJobFormScreen jobId={typeof id === "string" ? id : undefined} />
    </>
  );
}
