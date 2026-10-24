import type { Metadata } from "next";
import { Suspense } from "react";

import { DiaryPage } from "@/components/diary/diary-page";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Diary" };

export default function Page() {
  // ?add= (open quick-add for a meal) is request-time data, read inside Suspense.
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <DiaryPage />
    </Suspense>
  );
}
