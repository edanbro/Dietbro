import type { Metadata } from "next";
import { Suspense } from "react";

import { PlanPage } from "@/components/plan/plan-page";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Plan · Larder" };

export default function Page() {
  // PlanPage reads ?day and ?view, so it renders on the client below this boundary.
  return (
    <Suspense fallback={<Skeleton className="h-40" />}>
      <PlanPage />
    </Suspense>
  );
}
