import type { Metadata } from "next";

import { RecipeBrowser } from "@/components/recipe/recipe-browser";

export const metadata: Metadata = { title: "Recipes" };

export default function Page() {
  return <RecipeBrowser />;
}
