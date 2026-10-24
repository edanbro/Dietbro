"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, NativeSelect } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useMe, useRegions, useSaveRegion } from "@/lib/api/hooks";
import { currencySymbol, guessRegion } from "@/lib/region";
import type { Units } from "@/lib/units";

/** Where the user lives: currency, price estimates and dates follow it, and the units unless
 * the user picks them. */
export function RegionForm({ onSaved }: { onSaved?: () => void }) {
  const { data: me } = useMe();
  const { data: regions } = useRegions();
  const save = useSaveRegion();
  const [picked, setPicked] = useState<string | null>(null);
  const [pickedUnits, setPickedUnits] = useState<Units | null>(null);
  const guess = guessRegion();

  const saved = me?.region.saved ? me.region.country : null;
  const supported = (code: string) => (regions ?? []).some((r) => r.country === code);
  const fallback = guess.country && supported(guess.country) ? guess.country : "";
  const country = picked ?? saved ?? fallback;
  const option = regions?.find((r) => r.country === country);
  // Until picked here: the saved units, or the new country's when it changes.
  const units: Units =
    pickedUnits ??
    (me && country === saved ? me.region.units : country === "US" ? "us" : "metric");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!country) return;
    save.mutate(
      {
        country,
        timezone: guess.timezone,
        locale: guess.country === country ? guess.locale : null,
        units,
      },
      {
        onSuccess: (region) => {
          setPicked(null);
          setPickedUnits(null);
          toast.success(`Region set to ${region.name}`);
          onSaved?.();
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Region">
      <p className="text-sm text-muted-foreground">
        Used for your currency, estimated shop prices, dates and units. Change it any time in
        Profile.
      </p>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="country">Country</Label>
        <NativeSelect
          id="country"
          value={country}
          required
          onChange={(e) => setPicked(e.target.value)}
        >
          <option value="" disabled>
            Choose…
          </option>
          {(regions ?? []).map((r) => (
            <option key={r.country} value={r.country}>
              {r.name}
            </option>
          ))}
        </NativeSelect>
      </div>
      {option ? (
        <p className="text-sm">
          Prices in <strong>{currencySymbol(option.currency)}</strong> ({option.currency}),
          estimated for {option.name}.
        </p>
      ) : null}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="units">Weights and heights</Label>
        <NativeSelect
          id="units"
          value={units}
          onChange={(e) => setPickedUnits(e.target.value as Units)}
        >
          <option value="metric">Metric: grams, kilograms, centimetres</option>
          <option value="us">US: ounces, pounds, feet and inches</option>
        </NativeSelect>
      </div>
      <ErrorAlert error={save.error} />
      <Button type="submit" disabled={save.isPending || !country}>
        Save region
      </Button>
    </form>
  );
}
