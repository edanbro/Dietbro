"use client";

import { cn } from "cn";
import { ChevronRightIcon, CircleCheckIcon, EllipsisVerticalIcon, PinIcon } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import type { Meal } from "@/lib/api/hooks";
import { formatNumber, formatServings, servingsLabel } from "@/lib/format";

import { MealActions, type MealActionsProps } from "./meal-actions";
import { SLOT_ICON, SLOT_LABEL } from "./slots";
import { RecipeArt } from "@/components/recipe/recipe-art";

/**
 * A planned meal: photo (or the slot's icon), name, servings and the numbers that matter; a
 * check when it was marked eaten. With `actions`, an options button opens the meal's actions
 * under the card.
 */
export function MealCard({ meal, actions }: { meal: Meal; actions?: MealActionsProps }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const eaten = meal.status === "eaten";
  return (
    <div
      className={cn(
        "rounded-xl border bg-card shadow-xs motion-safe:transition-shadow hover:shadow-sm",
        eaten && "bg-muted/40",
      )}
    >
      <div className="flex items-center">
        <MealLink meal={meal} chevron={!actions} />
        {actions ? (
          <Button
            variant="ghost"
            className="mr-1.5 size-11"
            aria-label={`${SLOT_LABEL[meal.slot]} options`}
            aria-expanded={open}
            aria-controls={open ? panelId : undefined}
            onClick={() => setOpen(!open)}
          >
            <EllipsisVerticalIcon aria-hidden className="size-5" />
          </Button>
        ) : null}
      </div>
      {actions && open ? (
        <MealActions id={panelId} meal={meal} {...actions} onDone={() => setOpen(false)} />
      ) : null}
    </div>
  );
}

function MealLink({ meal, chevron }: { meal: Meal; chevron: boolean }) {
  const Icon = SLOT_ICON[meal.slot];
  return (
    <Link
      href={`/recipes/${meal.recipe.id}?servings=${meal.servings}`}
      className="flex min-w-0 flex-1 items-center gap-3 rounded-xl p-2.5 transition-colors hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <RecipeArt recipe={meal.recipe} className="size-16 shrink-0 rounded-lg" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Icon aria-hidden className="size-3.5" />
          {SLOT_LABEL[meal.slot]}
          {meal.locked ? (
            // Pinned by the user through the chat (a craving or swap): replans keep it.
            <span className="ml-1 flex items-center gap-0.5 font-medium text-foreground">
              <PinIcon aria-hidden className="size-3" />
              Pinned
            </span>
          ) : null}
          {meal.status === "eaten" ? (
            <span className="ml-1 flex items-center gap-0.5 font-medium text-emerald-700 dark:text-emerald-400">
              <CircleCheckIcon aria-hidden className="size-3" />
              Eaten
            </span>
          ) : null}
        </span>
        <span className="line-clamp-2 leading-snug font-medium">{meal.recipe.name}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          <span aria-hidden>{formatServings(meal.portions)}</span>
          <span className="sr-only">{servingsLabel(meal.portions)}</span> ·{" "}
          {formatNumber(meal.nutrition.kcal)} kcal · {formatNumber(meal.nutrition.protein_g)} g
          protein
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {formatNumber(meal.nutrition.carbs_g)} g carbs · {formatNumber(meal.nutrition.fat_g)} g
          fat
        </span>
        {meal.uses_pantry.length ? (
          <span className="line-clamp-1 text-xs text-emerald-700 dark:text-emerald-400">
            Uses your {meal.uses_pantry.slice(0, 2).join(", ").toLowerCase()}
            {meal.uses_pantry.length > 2 ? ` +${meal.uses_pantry.length - 2}` : ""}
          </span>
        ) : null}
      </div>
      {chevron ? (
        <ChevronRightIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      ) : null}
    </Link>
  );
}
