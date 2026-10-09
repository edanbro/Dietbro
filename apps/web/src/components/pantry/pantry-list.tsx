"use client";

import { Trash2Icon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type PantryItem, useDeletePantryItem, usePantry } from "@/lib/api/hooks";

const DAY_MS = 86_400_000;

/** Days until `isoDate` (local midnight to local midnight); negative when past. */
export function daysUntil(isoDate: string, today: Date = new Date()): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  const target = Date.UTC(y, m - 1, d);
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - now) / DAY_MS);
}

export function ExpiryBadge({ date, today }: { date: string | null; today?: Date }) {
  if (!date) return null;
  const days = daysUntil(date, today);
  if (days < 0) return <Badge variant="destructive">Expired</Badge>;
  if (days === 0) return <Badge variant="destructive">Use today</Badge>;
  if (days <= 3) return <Badge variant="secondary">{days === 1 ? "1 day" : `${days} days`}</Badge>;
  return <span className="text-xs text-muted-foreground">by {date}</span>;
}

export function formatAmount(item: Pick<PantryItem, "quantity" | "unit" | "grams" | "approx">) {
  const amount = `${item.quantity % 1 ? item.quantity.toFixed(1) : item.quantity} ${item.unit}`;
  const grams = item.unit === "g" ? "" : ` · ${Math.round(item.grams)} g`;
  return `${item.approx ? "~" : ""}${amount}${grams}`;
}

export function PantryList() {
  const { data, isPending } = usePantry();
  const remove = useDeletePantryItem();

  if (isPending) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
    );
  }
  if (!data?.length) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Your pantry is empty. Add what&apos;s in your fridge and cupboards.
      </p>
    );
  }
  return (
    <ul className="flex flex-col divide-y rounded-lg border" aria-label="Pantry items">
      {data.map((item) => (
        <li key={item.id} className="flex items-center gap-3 px-3 py-2.5">
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-sm">{item.food.description}</span>
            <span className="text-xs text-muted-foreground">{formatAmount(item)}</span>
          </div>
          <ExpiryBadge date={item.expires_on ?? null} />
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Remove ${item.food.description}`}
            disabled={remove.isPending}
            onClick={() => remove.mutate(item.id)}
          >
            <Trash2Icon />
          </Button>
        </li>
      ))}
    </ul>
  );
}
