"use client";

import { Button } from "@/components/ui/button";
import {
  type PantryItem,
  useConfirmPantryItem,
  useDeletePantryItem,
  usePantry,
} from "@/lib/api/hooks";
import { addDays, localISODate } from "@/lib/dates";
import { displayName } from "@/lib/food-name";

/** Days before each place's food is worth asking about: a fridge turns over fast, a freezer not. */
const ASK_AFTER: Record<PantryItem["storage"], number> = { fridge: 7, cupboard: 30, freezer: 60 };
const MOST_AT_ONCE = 5;
const EXPIRY_ALERT_DAYS = 3; // these are already under "Use soon"

/** The food most likely to be gone, oldest check first. ISO dates compare as strings. */
export function staleItems(items: PantryItem[], today: string): PantryItem[] {
  return items
    .filter(
      (item) =>
        item.checked_on < addDays(today, -ASK_AFTER[item.storage]) &&
        !(item.expires_on && item.expires_on < addDays(today, EXPIRY_ALERT_DAYS)),
    )
    .toSorted((a, b) => a.checked_on.localeCompare(b.checked_on))
    .slice(0, MOST_AT_ONCE);
}

/** Pantry-first plans are only as good as the pantry, and nobody records the last of the milk.
 * One tap per item keeps it true; nothing shows when there's nothing to ask. */
export function StillThere() {
  const { data } = usePantry();
  const confirm = useConfirmPantryItem();
  const remove = useDeletePantryItem();
  const items = staleItems(data ?? [], localISODate());
  if (!items.length) return null;
  const busy = confirm.isPending || remove.isPending;

  return (
    <section
      aria-labelledby="still-there-title"
      className="flex flex-col gap-2 rounded-xl border bg-card p-3"
    >
      <h2 id="still-there-title" className="text-sm font-semibold">
        Still in your kitchen?
      </h2>
      <ul className="flex flex-col gap-2">
        {items.map((item) => {
          const name = displayName(item.food.description, item.food.brand);
          return (
            <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="min-w-0 truncate">{name}</span>
              <span className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  aria-label={`${name}: still here`}
                  onClick={() => confirm.mutate(item.id)}
                >
                  Still here
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  aria-label={`${name}: used up`}
                  onClick={() => remove.mutate(item.id)}
                >
                  Used up
                </Button>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
