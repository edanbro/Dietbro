import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { RecipeEdit } from "@/components/recipe/recipe-edit";
import { Skeleton } from "@/components/ui/skeleton";

const ID = /^[1-9]\d{0,8}$/;

export const metadata: Metadata = { title: "Edit recipe" };

async function Edit({ params }: { params: PageProps<"/recipes/[id]/edit">["params"] }) {
  const { id } = await params;
  if (!ID.test(id)) notFound();
  return <RecipeEdit id={Number(id)} />;
}

export default function Page({ params }: PageProps<"/recipes/[id]/edit">) {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-3xl font-semibold">Edit recipe</h1>
      {/* The id is request-time data, read inside Suspense. */}
      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <Edit params={params} />
      </Suspense>
    </div>
  );
}
