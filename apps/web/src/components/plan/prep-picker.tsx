"use client";

import { ChefHatIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { Plan } from "@/lib/api/hooks";

const MAX = 4;

export type PrepChoice = { id: number; name: string; servings: number; meals: number };

/** This week's recipes still to eat (today on), with their servings added up across days
 * (everyone's, when the plan is for a household): cooking a recipe once for every meal it's
 * planned for is the point of batch cooking. */
export function prepChoices(plan: Plan, today: string): PrepChoice[] {
  const byRecipe = new Map<number, PrepChoice>();
  for (const day of plan.days) {
    if (day.date < today) continue;
    for (const meal of day.meals) {
      if (meal.status === "eaten") continue;
      const servings = meal.servings * plan.household;
      const seen = byRecipe.get(meal.recipe.id);
      if (seen) {
        seen.servings += servings;
        seen.meals += 1;
      } else {
        byRecipe.set(meal.recipe.id, {
          id: meal.recipe.id,
          name: meal.recipe.name,
          servings,
          meals: 1,
        });
      }
    }
  }
  return [...byRecipe.values()].sort((a, b) => b.meals - a.meals || a.name.localeCompare(b.name));
}

/** "Meal prep": pick 2-4 of the week's recipes and cook them together (/prep). */
export function PrepPicker({ plan, today }: { plan: Plan; today: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<number[]>([]);
  const choices = prepChoices(plan, today);
  if (!choices.length) return null;
  if (!open) {
    return (
      <Button variant="ghost" onClick={() => setOpen(true)}>
        <ChefHatIcon aria-hidden />
        Meal prep
      </Button>
    );
  }
  const toggle = (id: number) =>
    setPicked((all) => (all.includes(id) ? all.filter((x) => x !== id) : [...all, id]));
  const start = () => {
    const r = choices
      .filter((c) => picked.includes(c.id))
      .map((c) => `${c.id}x${Math.min(20, Math.round(c.servings * 2) / 2)}`)
      .join(",");
    router.push(`/prep?r=${r}`);
  };
  return (
    <fieldset className="flex w-full flex-col gap-3 rounded-lg border p-3">
      <legend className="px-1 text-sm font-medium">Cook ahead: pick up to {MAX}</legend>
      <ul className="flex flex-col gap-1.5">
        {choices.map((c) => {
          const checked = picked.includes(c.id);
          return (
            <li key={c.id}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={checked}
                  disabled={!checked && picked.length >= MAX}
                  onChange={() => toggle(c.id)}
                />
                <span className="min-w-0 flex-1">{c.name}</span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {c.meals} {c.meals === 1 ? "meal" : "meals"}, {c.servings}{" "}
                  {c.servings === 1 ? "serving" : "servings"}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      <div className="flex gap-2">
        <Button size="sm" disabled={!picked.length} onClick={start}>
          Start meal prep
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </fieldset>
  );
}
