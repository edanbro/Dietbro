import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { CookMode } from "@/components/recipe/cook-mode";
import { Skeleton } from "@/components/ui/skeleton";

const ID = /^[1-9]\d{0,8}$/;

export const metadata: Metadata = { title: "Cook" };

async function Cook({ params }: { params: PageProps<"/recipes/[id]/cook">["params"] }) {
  const { id } = await params;
  if (!ID.test(id)) notFound();
  return <CookMode id={Number(id)} />;
}

export default function Page({ params }: PageProps<"/recipes/[id]/cook">) {
  // The id and ?servings= are request-time data, read inside Suspense.
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <Cook params={params} />
    </Suspense>
  );
}
