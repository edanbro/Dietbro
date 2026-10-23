import type { Metadata } from "next";
import { Suspense } from "react";

import { RecipeBrowser } from "@/components/recipe/recipe-browser";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Recipes" };

export default function Page() {
  // ?pantry= is request-time data, read inside Suspense.
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <RecipeBrowser />
    </Suspense>
  );
}
