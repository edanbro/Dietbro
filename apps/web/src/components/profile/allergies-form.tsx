"use client";

import { XIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FoodPicker } from "@/components/food-picker";
import { ErrorAlert } from "@/components/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  type AllergiesIn,
  type FoodSummary,
  useAllergens,
  useAllergies,
  useSaveAllergies,
} from "@/lib/api/hooks";

type Allergen = NonNullable<AllergiesIn["allergens"]>[number];

/** Hard constraints: planned meals will never contain these. */
export function AllergiesForm({ onSaved }: { onSaved?: () => void }) {
  const { data: options } = useAllergens();
  const { data: saved } = useAllergies();
  const save = useSaveAllergies();
  const [allergens, setAllergens] = useState<Allergen[] | null>(null);
  const [avoid, setAvoid] = useState<FoodSummary[] | null>(null);

  const chosen = allergens ?? saved?.allergens ?? [];
  const avoided: FoodSummary[] = avoid ?? saved?.avoid_foods ?? [];

  function toggle(code: Allergen, on: boolean) {
    setAllergens(on ? [...chosen, code] : chosen.filter((c) => c !== code));
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    save.mutate(
      { allergens: chosen, avoid_food_ids: avoided.map((f) => f.id) },
      {
        onSuccess: () => {
          setAllergens(null);
          setAvoid(null);
          toast.success("Allergies saved");
          onSaved?.();
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Allergies">
      <p className="text-sm text-muted-foreground">
        These are strict: Larder will never plan a meal containing them.
      </p>
      <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <legend className="sr-only">Allergens</legend>
        {(options ?? []).map((a) => (
          <div key={a.code} className="flex items-center gap-3">
            <Checkbox
              id={`allergen-${a.code}`}
              checked={chosen.includes(a.code)}
              onCheckedChange={(on) => toggle(a.code, on)}
            />
            <Label htmlFor={`allergen-${a.code}`} className="font-normal">
              {a.label}
            </Label>
          </div>
        ))}
      </fieldset>
      <div className="flex flex-col gap-2">
        <Label htmlFor="avoid-search">Other foods to always avoid</Label>
        <FoodPicker
          id="avoid-search"
          placeholder="Search a food to avoid"
          onPick={(f) =>
            setAvoid(avoided.some((x) => x.id === f.id) ? avoided : [...avoided, f])
          }
        />
        <div className="flex flex-wrap gap-2">
          {avoided.map((f) => (
            <Badge key={f.id} variant="secondary" className="gap-1">
              {f.description}
              <button
                type="button"
                aria-label={`Remove ${f.description}`}
                onClick={() => setAvoid(avoided.filter((x) => x.id !== f.id))}
              >
                <XIcon className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      </div>
      <ErrorAlert error={save.error} />
      <Button type="submit" disabled={save.isPending}>
        {chosen.length || avoided.length ? "Save allergies" : "I have no allergies"}
      </Button>
    </form>
  );
}
