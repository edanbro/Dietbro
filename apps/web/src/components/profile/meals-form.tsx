"use client";

import { cn } from "cn";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type MealsIn, usePreferences, useSaveMeals } from "@/lib/api/hooks";

type Meal = keyof MealsIn;

const MAIN: [MealsIn["breakfast"], string][] = [
  ["plan", "Plan it"],
  ["own", "I'll sort it"],
  ["skip", "Skip it"],
];
const MEALS: { meal: Meal; label: string; options: [MealsIn[Meal], string][] }[] = [
  { meal: "breakfast", label: "Breakfast", options: MAIN },
  { meal: "lunch", label: "Lunch", options: MAIN },
  { meal: "dinner", label: "Dinner", options: MAIN },
  {
    meal: "snack",
    label: "Snacks",
    options: [
      ["plan", "When they help"],
      ["skip", "Never"],
    ],
  },
];

const DEFAULTS: MealsIn = { breakfast: "plan", lunch: "plan", dinner: "plan", snack: "plan" };

/**
 * Which meals the planner plans. A meal the user sorts out themselves (a canteen lunch) keeps
 * about its share of the day free; a skipped one leaves the day to the others. Saved on its
 * own, like busy nights, so the preferences form can't reset it.
 */
export function MealsForm() {
  const prefs = usePreferences();
  const save = useSaveMeals();
  const [picked, setPicked] = useState<MealsIn | null>(null);

  if (prefs.isPending) return <Skeleton className="h-40" />;
  if (prefs.error) return <ErrorAlert error={prefs.error} onRetry={() => void prefs.refetch()} />;
  if (!prefs.data) {
    return (
      <p className="text-sm text-muted-foreground">Set your preferences first (above).</p>
    );
  }
  const current: MealsIn = picked ?? { ...DEFAULTS, ...prefs.data.meals };

  function submit(e: React.FormEvent) {
    e.preventDefault();
    save.mutate(current, {
      onSuccess: () => {
        setPicked(null);
        toast.success("Saved: your next plan or change follows it");
      },
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Meals to plan">
      <p className="text-sm text-muted-foreground">
        For a meal you sort out yourself, like a lunch at work, about its share of your day is
        kept free. A skipped meal leaves the day to the others.
      </p>
      {MEALS.map(({ meal, label, options }) => (
        <fieldset key={meal} className="flex flex-col gap-2">
          <legend className="mb-2 text-sm font-medium">{label}</legend>
          <div className="flex flex-wrap gap-1.5">
            {options.map(([value, text]) => {
              const on = current[meal] === value;
              const id = `meal-${meal}-${value}`;
              return (
                <label
                  key={value}
                  htmlFor={id}
                  className={cn(
                    "inline-flex h-10 cursor-pointer items-center rounded-full border px-4 text-sm transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                    on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted",
                  )}
                >
                  <input
                    id={id}
                    type="radio"
                    name={`meal-${meal}`}
                    value={value}
                    checked={on}
                    onChange={() => setPicked({ ...current, [meal]: value })}
                    className="sr-only"
                  />
                  {text}
                </label>
              );
            })}
          </div>
        </fieldset>
      ))}
      <ErrorAlert error={save.error} />
      <div>
        <Button type="submit" disabled={save.isPending || picked === null}>
          {save.isPending ? "Saving…" : "Save meals"}
        </Button>
      </div>
    </form>
  );
}
