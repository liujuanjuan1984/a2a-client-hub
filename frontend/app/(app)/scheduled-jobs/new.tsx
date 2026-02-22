import { ScheduledJobFormScreen } from "@/screens/ScheduledJobFormScreen";
import { PageTitle } from "@/components/layout/PageTitle";

export default function NewScheduledJobPage() {
  return (
    <>
      <PageTitle title="New Job" />
      <ScheduledJobFormScreen />
    </>
  );
}
