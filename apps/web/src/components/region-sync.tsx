"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { type Me, useSaveRegion } from "@/lib/api/hooks";
import { setAppLocale } from "@/lib/locale";
import { currencySymbol, guessRegion } from "@/lib/region";

/**
 * Formats numbers and dates in the user's locale, and gives accounts made before regions
 * existed the region guessed from the browser (once, with a notice; setup asks new users).
 */
export function useRegionSync(me: Me | undefined, onSetup: boolean) {
  const save = useSaveRegion();
  const tried = useRef(false);

  if (me) setAppLocale(me.region.locale);

  useEffect(() => {
    if (!me || me.region.saved || onSetup || tried.current) return;
    const guess = guessRegion();
    if (!guess.country) return;
    tried.current = true;
    save.mutate(
      { country: guess.country, timezone: guess.timezone, locale: guess.locale },
      {
        onSuccess: (region) =>
          toast(`Region set to ${region.name} (${currencySymbol(region.currency)})`, {
            description: "Prices and dates follow it. Change it in Profile.",
          }),
      },
    );
  }, [me, onSetup, save]);
}
