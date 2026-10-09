import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";

import type { Meal } from "@/lib/api/hooks";
import { formatNumber, formatServings, servingsLabel } from "@/lib/format";

import { SLOT_ICON, SLOT_LABEL } from "./slots";

/** A planned meal: photo (or the slot's icon), name, servings and the numbers that matter. */
export function MealCard({ meal }: { meal: Meal }) {
  const Icon = SLOT_ICON[meal.slot];
  return (
    <Link
      href={`/recipes/${meal.recipe.id}`}
      className="flex items-center gap-3 rounded-xl border p-2.5 transition-colors hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      {meal.recipe.image_url ? (
        // Recipe photos come from many hosts at arbitrary sizes; a plain lazy <img> avoids
        // routing every one through the image optimizer.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={meal.recipe.image_url}
          alt=""
          loading="lazy"
          decoding="async"
          width={64}
          height={64}
          className="size-16 shrink-0 rounded-lg bg-muted object-cover"
        />
      ) : (
        <div
          data-testid="meal-placeholder"
          className="grid size-16 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground"
        >
          <Icon aria-hidden className="size-6" />
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Icon aria-hidden className="size-3.5" />
          {SLOT_LABEL[meal.slot]}
        </span>
        <span className="line-clamp-2 leading-snug font-medium">{meal.recipe.name}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          <span aria-hidden>{formatServings(meal.portions)}</span>
          <span className="sr-only">{servingsLabel(meal.portions)}</span> ·{" "}
          {formatNumber(meal.nutrition.kcal)} kcal · {formatNumber(meal.nutrition.protein_g)} g
          protein
        </span>
      </div>
      <ChevronRightIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}
