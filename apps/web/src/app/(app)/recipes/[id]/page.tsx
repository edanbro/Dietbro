import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { RecipePage } from "@/components/recipe/recipe-page";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Recipe · Larder" };

async function Recipe({ params }: { params: PageProps<"/recipes/[id]">["params"] }) {
  const { id } = await params;
  if (!/^[1-9]\d{0,8}$/.test(id)) notFound();
  return <RecipePage id={Number(id)} />;
}

export default function Page({ params }: PageProps<"/recipes/[id]">) {
  // The id is request-time data (no generateStaticParams), so it's read inside Suspense.
  return (
    <Suspense fallback={<Skeleton className="aspect-video w-full rounded-xl" />}>
      <Recipe params={params} />
    </Suspense>
  );
}
