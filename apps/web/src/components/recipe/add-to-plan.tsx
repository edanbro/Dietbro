"use client";

import { CalendarPlusIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/form-bits";
import { SLOT_LABEL } from "@/components/plan/slots";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { type Plan, type Recipe, useCurrentPlan, useReplan } from "@/lib/api/hooks";
import { localISODate, shortDate } from "@/lib/dates";

type Cell = { date: string; slot: Plan["days"][number]["meals"][number]["slot"]; label: string };

/** The planned meals this recipe could replace: today on, not eaten yet, a meal it suits. */
export function planCells(plan: Plan, recipe: Recipe, today: string): Cell[] {
  return plan.days.flatMap((day) =>
    day.date < today
      ? []
      : day.meals
          .filter(
            (m) =>
              m.status !== "eaten" &&
              m.recipe.id !== recipe.id &&
              (!recipe.meal_types.length || recipe.meal_types.includes(m.slot)),
          )
          .map((m) => ({
            date: day.date,
            slot: m.slot,
            label: `${day.date === today ? "Today" : shortDate(day.date)}, ${SLOT_LABEL[m.slot].toLowerCase()}, instead of ${m.recipe.name}`,
          })),
  );
}

/** Browsing used to end at "that looks good": this puts the recipe on the plan. It's a swap, so
 * the planner rebalances the day and the allergy checks still apply; the swap is pinned. */
export function AddToPlan({ recipe }: { recipe: Recipe }) {
  const { data: plan } = useCurrentPlan();
  const replan = useReplan();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState(0);
  const cells = plan ? planCells(plan, recipe, localISODate()) : [];
  if (!cells.length) return null;

  if (!open) {
    return (
      <Button variant="outline" className="w-full" onClick={() => setOpen(true)}>
        <CalendarPlusIcon aria-hidden />
        Add to my plan
      </Button>
    );
  }

  const cell = cells[Math.min(picked, cells.length - 1)];
  const add = () =>
    replan.mutate(
      [{ intent: "swap", when: { date: cell.date, slot: cell.slot }, recipe_id: recipe.id }],
      {
        onSuccess: (outcome) => {
          const result = outcome.results?.[0];
          if (result?.status === "failed") {
            toast.error(result.message);
            return;
          }
          toast.success(result?.message ?? "Added to your plan");
          setOpen(false);
        },
      },
    );

  return (
    <div className="flex flex-col gap-2 rounded-xl border bg-card p-3">
      <Label htmlFor="add-to-plan">When?</Label>
      <NativeSelect
        id="add-to-plan"
        value={String(picked)}
        onChange={(e) => setPicked(Number(e.target.value))}
      >
        {cells.map((c, i) => (
          <option key={`${c.date}-${c.slot}`} value={i}>
            {c.label}
          </option>
        ))}
      </NativeSelect>
      <div className="flex gap-2">
        <Button className="flex-1" disabled={replan.isPending} onClick={add}>
          {replan.isPending ? "Adding…" : "Add to my plan"}
        </Button>
        <Button variant="ghost" disabled={replan.isPending} onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
