"use client";

import { cn } from "cn";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type MealsIn, usePreferences, useSaveMeals } from "@/lib/api/hooks";

type Meal = keyof MealsIn;

const OPTIONS: [MealsIn["breakfast"], string][] = [
  ["plan", "Plan it"],
  ["own", "I'll sort it"],
  ["skip", "Skip it"],
];
const MAINS: { meal: Meal; label: string }[] = [
  { meal: "breakfast", label: "Breakfast" },
  { meal: "lunch", label: "Lunch" },
  { meal: "dinner", label: "Dinner" },
];
const SNACKS: { meal: Meal; label: string }[] = [
  { meal: "morning_snack", label: "Morning snack" },
  { meal: "snack", label: "Afternoon snack" },
  { meal: "evening_snack", label: "Evening snack" },
];

const DEFAULTS: MealsIn = {
  breakfast: "plan",
  morning_snack: "skip",
  lunch: "plan",
  snack: "plan",
  dinner: "plan",
  evening_snack: "skip",
};

function Choice({
  meal,
  label,
  current,
  onPick,
}: {
  meal: Meal;
  label: string;
  current: MealsIn;
  onPick: (next: MealsIn) => void;
}) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 text-sm font-medium">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {OPTIONS.map(([value, text]) => {
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
                onChange={() => onPick({ ...current, [meal]: value })}
                className="sr-only"
              />
              {text}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

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
      {MAINS.map(({ meal, label }) => (
        <Choice key={meal} meal={meal} label={label} current={current} onPick={setPicked} />
      ))}
      <h3 className="text-sm font-semibold">Snacks</h3>
      <p className="-mt-2 text-sm text-muted-foreground">
        A planned snack comes every day, and your meals get a little smaller to make room. Have as
        many as suit you.
      </p>
      {SNACKS.map(({ meal, label }) => (
        <Choice key={meal} meal={meal} label={label} current={current} onPick={setPicked} />
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
