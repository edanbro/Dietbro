import type { Metadata } from "next";
import { Suspense } from "react";

import { RecapPage } from "@/components/diary/recap-page";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Week in review" };

export default function Page() {
  // ?week= is request-time data, read inside Suspense.
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <RecapPage />
    </Suspense>
  );
}
