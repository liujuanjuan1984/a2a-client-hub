import { PageTitle } from "@/components/layout/PageTitle";
import { ScheduledJobFormScreen } from "@/screens/ScheduledJobFormScreen";

export default function NewScheduledJobPage() {
  return (
    <>
      <PageTitle title="New Job" />
      <ScheduledJobFormScreen />
    </>
  );
}
