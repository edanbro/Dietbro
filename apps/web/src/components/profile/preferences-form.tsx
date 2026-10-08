"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, NativeSelect } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  type PreferencesIn,
  useCuisines,
  usePreferences,
  useSavePreferences,
} from "@/lib/api/hooks";

type Diet = NonNullable<PreferencesIn["diet"]>;
type Rating = "like" | "dislike" | "neutral";

/** Soft preferences: the planner favours likes and avoids dislikes, but never forbids. */
export function PreferencesForm({ onSaved }: { onSaved?: () => void }) {
  const { data: cuisines } = useCuisines();
  const { data: saved } = usePreferences();
  const save = useSavePreferences();
  const [diet, setDiet] = useState<Diet | "" | null>(null);
  const [ratings, setRatings] = useState<Record<string, Rating> | null>(null);

  const currentDiet = diet ?? saved?.diet ?? "";
  const currentRatings: Record<string, Rating> = ratings ?? {
    ...Object.fromEntries((saved?.liked_cuisines ?? []).map((c) => [c, "like" as const])),
    ...Object.fromEntries((saved?.disliked_cuisines ?? []).map((c) => [c, "dislike" as const])),
  };
  const next: Record<Rating, Rating> = { neutral: "like", like: "dislike", dislike: "neutral" };

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const pick = (r: Rating) =>
      Object.entries(currentRatings)
        .filter(([, v]) => v === r)
        .map(([c]) => c);
    const payload: PreferencesIn = {
      diet: currentDiet || null,
      liked_cuisines: pick("like"),
      disliked_cuisines: pick("dislike"),
      liked_food_ids: saved?.liked_food_ids ?? [],
      disliked_food_ids: saved?.disliked_food_ids ?? [],
    };
    save.mutate(payload, {
      onSuccess: () => {
        setDiet(null);
        setRatings(null);
        toast.success("Preferences saved");
        onSaved?.();
      },
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Preferences">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="diet">Diet</Label>
        <NativeSelect
          id="diet"
          value={currentDiet}
          onChange={(e) => setDiet(e.target.value as Diet | "")}
        >
          <option value="">No restriction</option>
          <option value="vegetarian">Vegetarian</option>
          <option value="vegan">Vegan</option>
          <option value="pescatarian">Pescatarian</option>
        </NativeSelect>
      </div>
      <div className="flex flex-col gap-2">
        <Label>Cuisines (tap: like → dislike → no preference)</Label>
        <div className="flex flex-wrap gap-2">
          {(cuisines ?? []).map((c) => {
            const r = currentRatings[c] ?? "neutral";
            return (
              <Button
                key={c}
                type="button"
                size="sm"
                variant={r === "like" ? "default" : r === "dislike" ? "destructive" : "outline"}
                aria-pressed={r !== "neutral"}
                aria-label={`${c}: ${r}`}
                onClick={() => setRatings({ ...currentRatings, [c]: next[r] })}
              >
                {r === "like" ? "♥ " : r === "dislike" ? "✕ " : ""}
                {c}
              </Button>
            );
          })}
        </div>
      </div>
      <ErrorAlert error={save.error} />
      <Button type="submit" disabled={save.isPending}>
        Save preferences
      </Button>
    </form>
  );
}
