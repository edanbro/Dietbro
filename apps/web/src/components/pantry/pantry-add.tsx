"use client";

import { XIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FoodPicker } from "@/components/food-picker";
import { ErrorAlert, LabeledInput, NativeSelect } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  type FoodDetail,
  type FoodSummary,
  useAddPantryItem,
  useAllergens,
  useFood,
} from "@/lib/api/hooks";
import { allergenLabel } from "@/lib/format";

/**
 * Pick a food (or start from one, e.g. a scanned product), then how much (in any unit we can
 * weigh for it) and when it expires.
 */
export function PantryAdd({
  onAdded,
  initialFood = null,
}: {
  onAdded?: () => void;
  initialFood?: FoodSummary | null;
}) {
  const [food, setFood] = useState<FoodSummary | null>(initialFood);
  const [quantity, setQuantity] = useState("1");
  const [unit, setUnit] = useState("");
  const [expires, setExpires] = useState("");
  const [approx, setApprox] = useState(false);
  const { data: detail } = useFood(food?.id ?? null);
  const add = useAddPantryItem();

  const units = detail?.units ?? [];
  // Default to the food's own count unit ("large", "clove") when it has one, else grams.
  const chosenUnit = unit || units.find((u) => !["g", "kg"].includes(u.unit))?.unit || "g";

  function reset() {
    setFood(null);
    setQuantity("1");
    setUnit("");
    setExpires("");
    setApprox(false);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!food) return;
    const payload = {
      food_id: food.id,
      quantity: Number(quantity),
      unit: chosenUnit,
      approx,
      expires_on: expires || null,
    };
    add.mutate(payload, {
      onSuccess: (item) => {
        toast.success(`Added ${food.description} (${Math.round(item.grams)} g)`);
        reset();
        onAdded?.();
      },
    });
  }

  if (!food) {
    return <FoodPicker id="pantry-search" placeholder="Add food, e.g. onions" onPick={setFood} />;
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Add to pantry">
      <div className="flex flex-col gap-1.5 rounded-lg bg-muted p-3">
        <div className="flex items-start justify-between gap-2">
          <span className="text-sm font-medium">
            {food.brand ? `${food.brand} ` : ""}
            {food.description}
          </span>
          <button type="button" aria-label="Choose another food" onClick={reset}>
            <XIcon className="size-4" />
          </button>
        </div>
        {detail ? <FoodFacts detail={detail} /> : null}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <LabeledInput
          id="quantity"
          label="Quantity"
          type="number"
          inputMode="decimal"
          step="any"
          min="0"
          required
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="unit">Unit</Label>
          <NativeSelect id="unit" value={chosenUnit} onChange={(e) => setUnit(e.target.value)}>
            {(units.length ? units : [{ unit: "g", grams_each: 1 }]).map((u) => (
              <option key={u.unit} value={u.unit}>
                {u.unit}
                {u.grams_each && !["g", "kg"].includes(u.unit) ? ` (~${u.grams_each} g)` : ""}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <LabeledInput
        id="expires"
        label="Use by (optional)"
        type="date"
        value={expires}
        onChange={(e) => setExpires(e.target.value)}
      />
      <div className="flex items-center gap-3">
        <Switch id="approx" checked={approx} onCheckedChange={setApprox} />
        <Label htmlFor="approx" className="font-normal">
          Rough amount (I&apos;m guessing)
        </Label>
      </div>
      <ErrorAlert error={add.error} />
      <Button type="submit" disabled={add.isPending}>
        Add to pantry
      </Button>
    </form>
  );
}

/** What a food counts as for planning, what it contains and where the data comes from. */
function FoodFacts({ detail }: { detail: FoodDetail }) {
  const { data: options } = useAllergens();
  const label = (codes: readonly string[]) => codes.map((a) => allergenLabel(a, options)).join(", ");
  return (
    <div className="flex flex-col gap-1 text-xs text-muted-foreground">
      {detail.counts_as ? (
        <p>
          Counts as <span className="text-foreground">{detail.counts_as.description}</span> when
          planning.
        </p>
      ) : null}
      {detail.allergens.length ? <p>Contains: {label(detail.allergens)}</p> : null}
      {detail.may_contain.length ? <p>May contain: {label(detail.may_contain)}</p> : null}
      {detail.kind === "product" ? (
        <p>Product data is crowdsourced: always check the label for allergens.</p>
      ) : null}
      <p>Data: {detail.attribution}</p>
    </div>
  );
}
