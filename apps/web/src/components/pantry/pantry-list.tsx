"use client";

import { SearchIcon, Trash2Icon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, LabeledInput, NativeSelect } from "@/components/form-bits";

import { Badge } from "@/components/ui/badge";
import { ProductThumb } from "@/components/food-bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SkeletonRows } from "@/components/ui/skeleton";
import {
  type PantryItem,
  useDeletePantryItem,
  useFood,
  usePantry,
  useUpdatePantryItem,
} from "@/lib/api/hooks";
import { daysBetween, localISODate, shortDate } from "@/lib/dates";
import { EmptyState } from "@/components/empty-state";
import { foodName } from "@/lib/food-name";

function friendly(description: string): string {
  const { name, detail } = foodName(description);
  return detail ? `${name} · ${detail}` : name;
}

/** Days until `isoDate` (local midnight to local midnight); negative when past. */
export function daysUntil(isoDate: string, today: Date = new Date()): number {
  return daysBetween(localISODate(today), isoDate);
}

export function ExpiryBadge({ date, today }: { date: string | null; today?: Date }) {
  if (!date) return null;
  const days = daysUntil(date, today);
  if (days < 0) return <Badge variant="destructive">Expired</Badge>;
  if (days === 0) return <Badge variant="destructive">Use today</Badge>;
  if (days <= 3) return <Badge variant="secondary">{days === 1 ? "1 day" : `${days} days`}</Badge>;
  return <span className="text-xs text-muted-foreground">by {shortDate(date)}</span>;
}

export function formatAmount(item: Pick<PantryItem, "quantity" | "unit" | "grams" | "approx">) {
  const amount = `${item.quantity % 1 ? item.quantity.toFixed(1) : item.quantity} ${item.unit}`;
  const grams = item.unit === "g" ? "" : ` · ${Math.round(item.grams)} g`;
  return `${item.approx ? "~" : ""}${amount}${grams}`;
}

const PLACES = [
  { key: "fridge", label: "Fridge" },
  { key: "freezer", label: "Freezer" },
  { key: "cupboard", label: "Cupboard" },
] as const;
const UNDO_MS = 5000;

/**
 * The pantry by where things are kept, searchable; tap an item to edit it. Deleting waits a few
 * seconds so it can be undone.
 */
export function PantryList() {
  const { data, isPending } = usePantry();
  const remove = useDeletePantryItem();
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [hidden, setHidden] = useState<ReadonlySet<number>>(new Set());
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((t) => clearTimeout(t)); // leaving the page cancels deletes
  }, []);

  function removeLater(item: PantryItem) {
    setHidden((h) => new Set(h).add(item.id));
    const show = () =>
      setHidden((h) => {
        const next = new Set(h);
        next.delete(item.id);
        return next;
      });
    const timer = setTimeout(() => {
      timers.current.delete(item.id);
      remove.mutate(item.id, { onError: show });
    }, UNDO_MS);
    timers.current.set(item.id, timer);
    toast(`Removed ${item.food.description}`, {
      duration: UNDO_MS,
      action: {
        label: "Undo",
        onClick: () => {
          clearTimeout(timers.current.get(item.id));
          timers.current.delete(item.id);
          show();
        },
      },
    });
  }

  if (isPending) {
    return (
      <SkeletonRows count={5} />
    );
  }
  const items = (data ?? []).filter((i) => !hidden.has(i.id));
  if (!items.length) {
    return (
      <EmptyState art="pantry" title="Your pantry is empty">
        Add what&apos;s in your fridge and cupboards and plans will use it up first.
      </EmptyState>
    );
  }
  const q = query.trim().toLowerCase();
  const shown = q
    ? items.filter((i) => `${i.food.brand ?? ""} ${i.food.description}`.toLowerCase().includes(q))
    : items;
  return (
    <div className="flex flex-col gap-3">
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search your pantry"
          aria-label="Search your pantry"
          className="pl-8"
        />
      </div>
      {!shown.length ? (
        <p className="py-4 text-center text-sm text-muted-foreground">Nothing matches.</p>
      ) : null}
      {PLACES.map(({ key, label }) => {
        const group = shown.filter((i) => i.storage === key);
        if (!group.length) return null;
        return (
          <section key={key} aria-label={label} className="flex flex-col gap-1.5">
            <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {label} · {group.length}
            </h3>
            <ul className="flex flex-col divide-y rounded-lg border">
              {group.map((item) =>
                editing === item.id ? (
                  <li key={item.id} className="px-3 py-2.5">
                    <PantryEdit item={item} onDone={() => setEditing(null)} />
                  </li>
                ) : (
                  <li key={item.id} className="flex items-center gap-3 px-3 py-1.5">
                    <ProductThumb url={item.food.image_url} size={32} />
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 flex-col py-1 text-left"
                      aria-label={`Edit ${item.food.description}`}
                      onClick={() => setEditing(item.id)}
                    >
                      <span className="truncate text-sm">
                        {item.food.brand
                          ? `${item.food.brand} ${item.food.description}`
                          : friendly(item.food.description)}
                      </span>
                      <span className="text-xs text-muted-foreground">{formatAmount(item)}</span>
                    </button>
                    <ExpiryBadge date={item.expires_on ?? null} />
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove ${item.food.description}`}
                      onClick={() => removeLater(item)}
                    >
                      <Trash2Icon />
                    </Button>
                  </li>
                ),
              )}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** Change how much is left, the unit or the use-by date. */
function PantryEdit({ item, onDone }: { item: PantryItem; onDone: () => void }) {
  const update = useUpdatePantryItem();
  const { data: food } = useFood(item.food.id);
  const [quantity, setQuantity] = useState(String(item.quantity));
  const [unit, setUnit] = useState(item.unit);
  const [expires, setExpires] = useState(item.expires_on ?? "");
  const units = food?.units.map((u) => u.unit) ?? [];
  const options = units.includes(item.unit) ? units : [item.unit, ...units];

  function submit(e: React.FormEvent) {
    e.preventDefault();
    update.mutate(
      { id: item.id, quantity: Number(quantity), unit, expires_on: expires || null },
      {
        onSuccess: () => {
          toast.success(`Updated ${item.food.description}`);
          onDone();
        },
      },
    );
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-3"
      aria-label={`Edit ${item.food.description}`}
    >
      <span className="text-sm font-medium">{item.food.description}</span>
      <div className="grid grid-cols-2 gap-3">
        <LabeledInput
          id={`qty-${item.id}`}
          label="Quantity left"
          type="number"
          inputMode="decimal"
          step="any"
          min="0"
          required
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`unit-${item.id}`}>Unit</Label>
          <NativeSelect
            id={`unit-${item.id}`}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          >
            {options.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <LabeledInput
        id={`expires-${item.id}`}
        label="Use by"
        type="date"
        value={expires}
        onChange={(e) => setExpires(e.target.value)}
      />
      <ErrorAlert error={update.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={update.isPending}>
          Save
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
