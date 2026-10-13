"use client";

import { useMe } from "@/lib/api/hooks";

/** Where the price estimates are for (the user's region). */
export function PriceNote({ children }: { children?: React.ReactNode }) {
  const { data: me } = useMe();
  const where = me ? ` in ${me.region.name}` : "";
  return (
    <p className="text-xs text-muted-foreground">
      {children}
      {children ? " " : null}Prices are estimates of typical supermarket prices{where}.
    </p>
  );
}
