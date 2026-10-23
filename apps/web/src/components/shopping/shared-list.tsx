"use client";

import { cn } from "cn";
import { useEffect, useRef, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { PUBLIC_API_URL } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";
import { aisle } from "@/lib/aisles";
import { addDays, dateRange } from "@/lib/dates";
import { foodName } from "@/lib/food-name";
import { formatGrams } from "@/lib/format";

export type SharedList = components["schemas"]["SharedListOut"];
type Item = components["schemas"]["SharedItemOut"];
type Shared = components["schemas"]["SharedOut"];

/** How often the list is read again, so ticks from the others show up. */
export const POLL_MS = 15_000;

function withItem(list: SharedList, foodId: number, checked: boolean): SharedList {
  return {
    ...list,
    items: list.items.map((i) => (i.food_id === foodId ? { ...i, checked } : i)),
  };
}

function withExtra(list: SharedList, id: number, checked: boolean): SharedList {
  return {
    ...list,
    extras: list.extras.map((e) => (e.id === id ? { ...e, checked } : e)),
  };
}

function byAisle(items: Item[]): [string, Item[]][] {
  const groups = new Map<string, Item[]>();
  for (const item of items) {
    const key = aisle(item.category);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()];
}

function Row({
  id,
  name,
  amount,
  checked,
  onChange,
}: {
  id: string;
  name: string;
  amount?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <Checkbox
        id={id}
        checked={checked}
        aria-describedby={amount ? `${id}-amount` : undefined}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Label
          htmlFor={id}
          className={cn("leading-snug font-normal", checked && "text-muted-foreground line-through")}
        >
          {name}
        </Label>
        {amount ? (
          <span id={`${id}-amount`} className="text-xs text-muted-foreground">
            {amount}
          </span>
        ) : null}
      </div>
    </li>
  );
}

/**
 * A shopping list shared by link (/s/<token>): anyone with it ticks things off as they shop,
 * no sign-in. Ticks show at once and are saved; the list is read again every few seconds while
 * the page is open, so everyone sees the same one.
 */
export function SharedShoppingList({ token, initial }: { token: string; initial: SharedList }) {
  const [list, setList] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const saving = useRef(0); // ticks on their way: a poll mustn't undo them
  const base = `${PUBLIC_API_URL}/public/share/${encodeURIComponent(token)}`;

  useEffect(() => {
    const timer = setInterval(() => {
      if (saving.current || document.visibilityState !== "visible") return;
      void fetch(base, { cache: "no-store" })
        .then(async (res) => (res.ok ? ((await res.json()) as Shared) : null))
        .then((shared) => {
          if (shared?.shopping && !saving.current) setList(shared.shopping);
        })
        .catch(() => {}); // no signal in the shop: keep what's shown
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [base]);

  async function save(path: string, checked: boolean, undo: (l: SharedList) => SharedList) {
    saving.current += 1;
    setError(null);
    try {
      const res = await fetch(`${base}/${path}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checked }),
      });
      if (!res.ok) throw new Error(res.status === 404 ? "gone" : "failed");
      const fresh = (await res.json()) as SharedList;
      saving.current -= 1;
      if (!saving.current) setList(fresh);
    } catch (e) {
      saving.current -= 1;
      setList(undo);
      setError(
        e instanceof Error && e.message === "gone"
          ? "This list isn't shared any more."
          : "Couldn't save that tick. Check your connection and try again.",
      );
    }
  }

  const tickItem = (item: Item, checked: boolean) => {
    setList((l) => withItem(l, item.food_id, checked));
    void save(`items/${item.food_id}`, checked, (l) => withItem(l, item.food_id, !checked));
  };
  const tickExtra = (id: number, checked: boolean) => {
    setList((l) => withExtra(l, id, checked));
    void save(`extras/${id}`, checked, (l) => withExtra(l, id, !checked));
  };

  const toBuy = list.items.filter((i) => !i.staple);
  const staples = list.items.filter((i) => i.staple);
  const ticked = toBuy.filter((i) => i.checked).length + list.extras.filter((e) => e.checked).length;
  const total = toBuy.length + list.extras.length;
  const amount = (item: Item) => {
    const { detail } = foodName(item.name);
    return item.staple
      ? (detail ?? undefined)
      : [formatGrams(item.grams), item.approx_units, detail].filter(Boolean).join(" · ");
  };

  return (
    <article className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold">Shopping list</h1>
        <p className="text-muted-foreground">
          For {dateRange(list.start, addDays(list.start, 6))}
          {list.household > 1 ? `, ${list.household} people` : ""}
        </p>
        <p className="text-sm text-muted-foreground">
          Tick things off as you shop: everyone with this link sees the same list.
        </p>
      </header>
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {ticked} of {total} ticked
      </p>
      {byAisle(toBuy).map(([name, items], n) => (
        <section key={name} aria-labelledby={`shared-aisle-${n}`} className="flex flex-col gap-2">
          <h2 id={`shared-aisle-${n}`} className="text-sm font-semibold">
            {name}
          </h2>
          <ul className="flex flex-col divide-y rounded-lg border bg-card">
            {items.map((item) => (
              <Row
                key={item.food_id}
                id={`shared-${item.food_id}`}
                name={foodName(item.name).name}
                amount={amount(item)}
                checked={item.checked}
                onChange={(checked) => tickItem(item, checked)}
              />
            ))}
          </ul>
        </section>
      ))}
      {list.extras.length ? (
        <section aria-labelledby="shared-extras" className="flex flex-col gap-2">
          <h2 id="shared-extras" className="text-sm font-semibold">
            Also
          </h2>
          <ul className="flex flex-col divide-y rounded-lg border bg-card">
            {list.extras.map((e) => (
              <Row
                key={e.id}
                id={`shared-extra-${e.id}`}
                name={e.name}
                checked={e.checked}
                onChange={(checked) => tickExtra(e.id, checked)}
              />
            ))}
          </ul>
        </section>
      ) : null}
      {staples.length ? (
        <section aria-labelledby="shared-staples" className="flex flex-col gap-2">
          <h2 id="shared-staples" className="text-sm font-semibold">
            Check you have
          </h2>
          <ul className="flex flex-col divide-y rounded-lg border bg-card">
            {staples.map((item) => (
              <Row
                key={item.food_id}
                id={`shared-${item.food_id}`}
                name={foodName(item.name).name}
                amount={amount(item)}
                checked={item.checked}
                onChange={(checked) => tickItem(item, checked)}
              />
            ))}
          </ul>
        </section>
      ) : null}
      {!total && !staples.length ? (
        <p className="text-center text-sm text-muted-foreground">Nothing to buy this week.</p>
      ) : null}
    </article>
  );
}
