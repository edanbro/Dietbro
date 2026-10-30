"use client";

import { useRouter } from "next/navigation";

import { ErrorAlert } from "@/components/form-bits";
import { Skeleton } from "@/components/ui/skeleton";
import { type ImportDraft, type Recipe, type Slot, useRecipe } from "@/lib/api/hooks";

import { DraftForm } from "./recipe-import";

// The draft's meal: the main one when a recipe suits several.
const PREFERRED: Slot[] = ["dinner", "lunch", "breakfast", "snack"];

/** A recipe as an editable draft (the import form's shape). */
export function draftOf(recipe: Recipe): ImportDraft {
  return {
    name: recipe.name,
    slot: PREFERRED.find((s) => recipe.meal_types.includes(s)) ?? "dinner",
    servings: Math.min(8, Math.max(1, recipe.servings ?? 2)),
    cuisine: recipe.cuisine,
    ingredients: recipe.ingredients
      .slice(0, 25)
      .map((i) => ({ line: "", name: i.name, quantity: i.measure })),
    instructions: recipe.instructions.slice(0, 4000),
    image_url: recipe.image_url,
    source_url: recipe.source_url,
  };
}

/**
 * Change a recipe. The user's own (imported or typed in) changes in place;
 * a catalogue recipe is saved as their own copy, so nobody else's changes.
 */
export function RecipeEdit({ id }: { id: number }) {
  const router = useRouter();
  const { data: recipe, isPending, error, refetch } = useRecipe(id);
  if (isPending) {
    return (
      <div className="flex flex-col gap-3" aria-busy>
        <Skeleton className="h-10" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (error) return <ErrorAlert error={error} onRetry={() => void refetch()} />;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        {recipe.generated
          ? "Your recipe changes for every plan from now on. Meals already planned keep their numbers."
          : "This saves your own copy; the original stays in the catalogue. Only you can see your copy."}
      </p>
      <DraftForm
        initial={draftOf(recipe)}
        editing={id}
        onBack={() => router.push(`/recipes/${id}`)}
      />
    </div>
  );
}
