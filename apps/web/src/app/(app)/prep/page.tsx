import type { Metadata } from "next";
import { Suspense } from "react";

import { MealPrep } from "@/components/recipe/meal-prep";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Meal prep" };

export default function Page() {
  // ?r= is request-time data, read inside Suspense.
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <MealPrep />
    </Suspense>
  );
}
