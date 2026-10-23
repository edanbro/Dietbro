import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { RecipePage } from "@/components/recipe/recipe-page";
import { createApiClient } from "@/lib/api/client";
import { Skeleton } from "@/components/ui/skeleton";

const ID = /^[1-9]\d{0,8}$/;

/** The dish's name as the page title (shared recipes; a user's own ones stay "Recipe"). */
export async function generateMetadata({ params }: PageProps<"/recipes/[id]">): Promise<Metadata> {
  const { id } = await params;
  if (!ID.test(id)) return { title: "Recipe" };
  try {
    const { data } = await createApiClient().GET("/recipes/{recipe_id}", {
      params: { path: { recipe_id: Number(id) } },
      signal: AbortSignal.timeout(2000),
    });
    return { title: data?.name ?? "Recipe" };
  } catch {
    return { title: "Recipe" };
  }
}

async function Recipe({ params }: { params: PageProps<"/recipes/[id]">["params"] }) {
  const { id } = await params;
  if (!ID.test(id)) notFound();
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
