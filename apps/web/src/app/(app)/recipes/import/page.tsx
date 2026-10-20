import type { Metadata } from "next";

import { RecipeImport } from "@/components/recipe/recipe-import";

export const metadata: Metadata = { title: "Import a recipe" };

export default function Page() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-3xl font-semibold">Import a recipe</h1>
      <RecipeImport />
    </div>
  );
}
