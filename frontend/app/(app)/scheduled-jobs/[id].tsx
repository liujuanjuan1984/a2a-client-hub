import { useLocalSearchParams } from "expo-router";

import { PageTitle } from "@/components/layout/PageTitle";
import { ScheduledJobFormScreen } from "@/screens/ScheduledJobFormScreen";

export default function EditScheduledJobPage() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  return (
    <>
      <PageTitle title="Edit Job" />
      <ScheduledJobFormScreen jobId={typeof id === "string" ? id : undefined} />
    </>
  );
}
