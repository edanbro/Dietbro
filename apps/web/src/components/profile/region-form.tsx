"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, NativeSelect } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useMe, useRegions, useSaveRegion } from "@/lib/api/hooks";
import { currencySymbol, guessRegion } from "@/lib/region";

/** Where the user lives: currency, price estimates and dates follow it. */
export function RegionForm({ onSaved }: { onSaved?: () => void }) {
  const { data: me } = useMe();
  const { data: regions } = useRegions();
  const save = useSaveRegion();
  const [picked, setPicked] = useState<string | null>(null);
  const guess = guessRegion();

  const saved = me?.region.saved ? me.region.country : null;
  const supported = (code: string) => (regions ?? []).some((r) => r.country === code);
  const fallback = guess.country && supported(guess.country) ? guess.country : "";
  const country = picked ?? saved ?? fallback;
  const option = regions?.find((r) => r.country === country);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!country) return;
    save.mutate(
      {
        country,
        timezone: guess.timezone,
        locale: guess.country === country ? guess.locale : null,
      },
      {
        onSuccess: (region) => {
          setPicked(null);
          toast.success(`Region set to ${region.name}`);
          onSaved?.();
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Region">
      <p className="text-sm text-muted-foreground">
        Used for your currency, estimated shop prices and dates. Change it any time in Profile.
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
      <ErrorAlert error={save.error} />
      <Button type="submit" disabled={save.isPending || !country}>
        Save region
      </Button>
    </form>
  );
}
