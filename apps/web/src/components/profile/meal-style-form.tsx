"use client";

import { cn } from "cn";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { Skeleton } from "@/components/ui/skeleton";
import { type MealStyle, usePreferences, useSaveMealStyle } from "@/lib/api/hooks";

const STYLES: { value: MealStyle; label: string; hint: string }[] = [
  {
    value: "everyday",
    label: "Familiar meals",
    hint: "Sandwiches, soups, pasta, roasts, curries: what most people have in a normal week.",
  },
  {
    value: "mix",
    label: "A mix",
    hint: "Mostly familiar meals, with something new from around the world most weeks.",
  },
  {
    value: "adventurous",
    label: "Surprise me",
    hint: "Anything from the whole recipe collection, however unusual.",
  },
];

/**
 * How far from everyday meals the planner goes. Saved as soon as it's picked, on its own like
 * the meals below it, so the preferences form can't reset it.
 */
export function MealStyleForm() {
  const prefs = usePreferences();
  const save = useSaveMealStyle();

  if (prefs.isPending) return <Skeleton className="h-40" />;
  if (prefs.error || !prefs.data) return null;
  const current = save.isPending ? save.variables : prefs.data.meal_style;

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 text-sm font-medium">What kind of meals?</legend>
      {STYLES.map(({ value, label, hint }) => {
        const on = current === value;
        const id = `meal-style-${value}`;
        return (
          <label
            key={value}
            htmlFor={id}
            className={cn(
              "flex cursor-pointer flex-col gap-0.5 rounded-xl border p-3 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
              on ? "border-primary bg-primary/5" : "hover:bg-muted",
            )}
          >
            <input
              id={id}
              type="radio"
              name="meal-style"
              value={value}
              checked={on}
              onChange={() =>
                save.mutate(value, {
                  onSuccess: () => toast.success("Saved: your next plan or change follows it"),
                })
              }
              className="sr-only"
            />
            <span className="text-sm font-medium">{label}</span>
            <span className="text-sm text-muted-foreground">{hint}</span>
          </label>
        );
      })}
      <ErrorAlert error={save.error} />
    </fieldset>
  );
}
