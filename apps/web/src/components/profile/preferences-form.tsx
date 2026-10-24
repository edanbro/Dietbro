"use client";

import { XIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FoodPicker } from "@/components/food-picker";
import { ErrorAlert, NativeSelect } from "@/components/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  type FoodSummary,
  type PreferencesIn,
  useCuisines,
  usePreferences,
  useSavePreferences,
} from "@/lib/api/hooks";
import { displayName } from "@/lib/food-name";

type Diet = NonNullable<PreferencesIn["diet"]>;
type Rating = "like" | "dislike" | "neutral";

/** Foods picked for a list, shown as removable chips. */
/** Shown first; the rest (TheMealDB has dozens of areas) sit behind "All cuisines". */
const COMMON_CUISINES = new Set([
  "American",
  "British",
  "Chinese",
  "French",
  "Greek",
  "Indian",
  "Irish",
  "Italian",
  "Japanese",
  "Korean",
  "Mexican",
  "Moroccan",
  "Spanish",
  "Thai",
  "Turkish",
  "Vietnamese",
]);

function FoodChips({
  id,
  label,
  placeholder,
  foods,
  onChange,
}: {
  id: string;
  label: string;
  placeholder: string;
  foods: FoodSummary[];
  onChange: (foods: FoodSummary[]) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <FoodPicker
        id={id}
        scope="generic"
        placeholder={placeholder}
        onPick={(f) => onChange(foods.some((x) => x.id === f.id) ? foods : [...foods, f])}
      />
      {foods.length ? (
        <ul className="flex flex-wrap gap-2" aria-label={label}>
          {foods.map((f) => (
            <li key={f.id}>
              <Badge variant="secondary" className="gap-1">
                {displayName(f.description, f.brand)}
                <button
                  type="button"
                  className="relative after:absolute after:-inset-3 after:content-['']"
                  aria-label={`Remove ${f.description}`}
                  onClick={() => onChange(foods.filter((x) => x.id !== f.id))}
                >
                  <XIcon className="size-3" />
                </button>
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Soft preferences: the planner favours likes and avoids dislikes, but never forbids. */
export function PreferencesForm({ onSaved }: { onSaved?: () => void }) {
  const { data: cuisines } = useCuisines();
  const [allCuisines, setAllCuisines] = useState(false);
  const { data: saved } = usePreferences();
  const save = useSavePreferences();
  const [diet, setDiet] = useState<Diet | "" | null>(null);
  const [ratings, setRatings] = useState<Record<string, Rating> | null>(null);
  const [liked, setLiked] = useState<FoodSummary[] | null>(null);
  const [disliked, setDisliked] = useState<FoodSummary[] | null>(null);

  const currentDiet = diet ?? saved?.diet ?? "";
  const currentRatings: Record<string, Rating> = ratings ?? {
    ...Object.fromEntries((saved?.liked_cuisines ?? []).map((c) => [c, "like" as const])),
    ...Object.fromEntries((saved?.disliked_cuisines ?? []).map((c) => [c, "dislike" as const])),
  };
  const likedFoods = liked ?? saved?.liked_foods ?? [];
  const dislikedFoods = disliked ?? saved?.disliked_foods ?? [];
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
      liked_food_ids: likedFoods.map((f) => f.id),
      disliked_food_ids: dislikedFoods.map((f) => f.id),
    };
    save.mutate(payload, {
      onSuccess: () => {
        setDiet(null);
        setRatings(null);
        setLiked(null);
        setDisliked(null);
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
          {(cuisines ?? [])
            .filter((c) => allCuisines || COMMON_CUISINES.has(c) || currentRatings[c])
            .map((c) => {
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
          {(cuisines?.length ?? 0) > COMMON_CUISINES.size ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-expanded={allCuisines}
              onClick={() => setAllCuisines(!allCuisines)}
            >
              {allCuisines ? "Fewer" : `All ${cuisines?.length} cuisines`}
            </Button>
          ) : null}
        </div>
      </div>
      <FoodChips
        id="liked-foods"
        label="Foods you love"
        placeholder="e.g. salmon, mushrooms"
        foods={likedFoods}
        onChange={setLiked}
      />
      <FoodChips
        id="disliked-foods"
        label="Foods you'd rather not have"
        placeholder="e.g. olives, coriander"
        foods={dislikedFoods}
        onChange={setDisliked}
      />
      <p className="text-xs text-muted-foreground">
        These steer the planner; for anything you must never eat, use Allergies.
      </p>
      <ErrorAlert error={save.error} />
      <Button type="submit" disabled={save.isPending}>
        Save preferences
      </Button>
    </form>
  );
}
