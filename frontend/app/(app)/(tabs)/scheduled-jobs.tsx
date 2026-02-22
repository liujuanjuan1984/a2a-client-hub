import { PageTitle } from "@/components/layout/PageTitle";
import { ScheduledJobsScreen } from "@/screens/ScheduledJobsScreen";

export default function ScheduledJobsPage() {
  return (
    <>
      <PageTitle title="Scheduled Jobs" />
      <ScheduledJobsScreen />
    </>
  );
}
