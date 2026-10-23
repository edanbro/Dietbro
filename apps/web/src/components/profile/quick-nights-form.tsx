"use client";

import { cn } from "cn";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, NativeSelect } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { type QuickNightsIn, usePreferences, useSaveQuickNights } from "@/lib/api/hooks";

type Minutes = QuickNightsIn["minutes"];

// Weekdays as the API numbers them: 0 = Monday.
const DAYS = [
  ["Mon", "Monday"],
  ["Tue", "Tuesday"],
  ["Wed", "Wednesday"],
  ["Thu", "Thursday"],
  ["Fri", "Friday"],
  ["Sat", "Saturday"],
  ["Sun", "Sunday"],
] as const;
const MINUTES: Minutes[] = [20, 30, 45];

/**
 * Busy nights: weekdays whose dinner the planner keeps quick (a recipe estimated to take at
 * most 20, 30 or 45 minutes). Saved on their own, so the preferences form can't reset them.
 */
export function QuickNightsForm() {
  const prefs = usePreferences();
  const save = useSaveQuickNights();
  const [days, setDays] = useState<number[] | null>(null);
  const [minutes, setMinutes] = useState<Minutes | null>(null);

  if (prefs.isPending) return <Skeleton className="h-28" />;
  if (prefs.error) return <ErrorAlert error={prefs.error} onRetry={() => void prefs.refetch()} />;
  if (!prefs.data) {
    return (
      <p className="text-sm text-muted-foreground">Set your preferences first (above).</p>
    );
  }
  const chosen = days ?? prefs.data.quick_days ?? [];
  const limit = minutes ?? ((prefs.data.quick_minutes ?? 30) as Minutes);
  const changed = days !== null || minutes !== null;
  const toggle = (d: number) =>
    setDays(
      chosen.includes(d) ? chosen.filter((x) => x !== d) : [...chosen, d].sort((a, b) => a - b),
    );

  function submit(e: React.FormEvent) {
    e.preventDefault();
    save.mutate(
      { days: chosen, minutes: limit },
      {
        onSuccess: () => {
          setDays(null);
          setMinutes(null);
          toast.success(
            chosen.length ? "Busy nights saved: your next plan keeps them quick" : "Busy nights off",
          );
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        On these nights, dinner is a recipe that takes about {limit} minutes or less. New plans
        follow it; a plan you already have stays as it is.
      </p>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-2 text-sm font-medium">Quick dinners on</legend>
        <div className="grid max-w-md grid-cols-7 gap-1.5">
          {DAYS.map(([short, long], d) => {
            const on = chosen.includes(d);
            return (
              <button
                key={short}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(d)}
                className={cn(
                  "inline-flex h-10 items-center justify-center rounded-full border text-sm transition-colors",
                  on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted",
                )}
              >
                {/* "Mon" on screen, "Monday" to a screen reader. */}
                {short}
                <span className="sr-only">{long.slice(short.length)}</span>
              </button>
            );
          })}
        </div>
      </fieldset>
      <div className="flex max-w-xs flex-col gap-1.5">
        <Label htmlFor="quick-minutes">At most</Label>
        <NativeSelect
          id="quick-minutes"
          value={limit}
          onChange={(e) => setMinutes(Number(e.target.value) as Minutes)}
        >
          {MINUTES.map((m) => (
            <option key={m} value={m}>
              {m} minutes
            </option>
          ))}
        </NativeSelect>
      </div>
      <ErrorAlert error={save.error} />
      <div>
        <Button type="submit" disabled={save.isPending || !changed}>
          {save.isPending ? "Saving…" : "Save busy nights"}
        </Button>
      </div>
    </form>
  );
}
