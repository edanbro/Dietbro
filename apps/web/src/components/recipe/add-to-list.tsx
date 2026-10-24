"use client";

import { ListPlusIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { type Recipe, useAddShoppingExtras, useUnits } from "@/lib/api/hooks";
import type { Units } from "@/lib/units";
import { scaledAmount, scaleFactor } from "@/lib/cooking";

// What nearly every kitchen has: listed, but not ticked to buy.
const BASICS = /^(?:salt|(?:black |ground )?pepper|(?:cold |hot |boiling |warm )?water|ice)\b/i;
const MAX_NAME = 120;

export type ShoppingLine = { index: number; name: string; amount: string; basic: boolean };

/** The recipe's ingredients not in the pantry, with their amounts at `factor`. */
export function shoppingLines(
  recipe: Recipe,
  factor: number,
  units: Units = "metric",
): ShoppingLine[] {
  return recipe.ingredients.flatMap((ing, index) =>
    ing.in_pantry
      ? []
      : [
          {
            index,
            name: ing.name.charAt(0).toUpperCase() + ing.name.slice(1),
            amount: scaledAmount(ing, factor, units),
            basic: BASICS.test(ing.name.trim()),
          },
        ],
  );
}

/** "Chicken breast (600 g)": one shopping-list item. */
export function itemName(line: ShoppingLine): string {
  const text = line.amount ? `${line.name} (${line.amount})` : line.name;
  return text.length <= MAX_NAME ? text : `${text.slice(0, MAX_NAME - 1)}…`;
}

/**
 * "Add to shopping list" for a recipe that isn't on the plan (or more of one that is): the
 * ingredients not in the pantry, at `servings` (the recipe's own when null), each ticked but
 * the basics; added to the user's own list in one go.
 */
export function AddToList({ recipe, servings }: { recipe: Recipe; servings: number | null }) {
  const router = useRouter();
  const add = useAddShoppingExtras();
  const [open, setOpen] = useState(false);
  const units = useUnits();
  const factor = scaleFactor(servings ?? recipe.servings ?? 1, recipe.servings);
  const lines = shoppingLines(recipe, factor, units);
  const [picked, setPicked] = useState<ReadonlySet<number>>(
    () => new Set(lines.filter((l) => !l.basic).map((l) => l.index)),
  );
  if (!lines.length) return null;
  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <ListPlusIcon aria-hidden />
        Add to shopping list
      </Button>
    );
  }
  const chosen = lines.filter((l) => picked.has(l.index));
  const inPantry = recipe.ingredients.length - lines.length;
  const toggle = (index: number) =>
    setPicked((all) => {
      const next = new Set(all);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  const submit = () =>
    add.mutate(chosen.map(itemName), {
      onSuccess: (added) => {
        setOpen(false);
        if (!added.length) {
          toast.success("Those are on your shopping list already");
          return;
        }
        toast.success(
          `Added ${added.length} ${added.length === 1 ? "item" : "items"} to your shopping list`,
          { action: { label: "Open list", onClick: () => router.push("/plan/shopping") } },
        );
      },
    });

  return (
    <fieldset className="flex w-full flex-col gap-3 rounded-lg border p-3">
      <legend className="px-1 text-sm font-medium">Add to your shopping list</legend>
      {inPantry ? (
        <p className="text-xs text-muted-foreground">
          {inPantry} {inPantry === 1 ? "ingredient is" : "ingredients are"} in your pantry
          already.
        </p>
      ) : null}
      <ul className="flex flex-col gap-1.5">
        {lines.map((l) => (
          <li key={l.index}>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 accent-primary"
                checked={picked.has(l.index)}
                onChange={() => toggle(l.index)}
              />
              <span className="min-w-0 flex-1">{l.name}</span>
              {l.amount ? (
                <span className="text-xs text-muted-foreground tabular-nums">{l.amount}</span>
              ) : null}
            </label>
          </li>
        ))}
      </ul>
      <ErrorAlert error={add.error} />
      <div className="flex gap-2">
        <Button size="sm" disabled={!chosen.length || add.isPending} onClick={submit}>
          {add.isPending
            ? "Adding…"
            : `Add ${chosen.length} ${chosen.length === 1 ? "item" : "items"}`}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </fieldset>
  );
}
