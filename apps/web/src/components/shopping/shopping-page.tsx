"use client";

import { cn } from "cn";
import {
  ArrowLeftIcon,
  PackageCheckIcon,
  ShareIcon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { PriceNote } from "@/components/price-note";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton, SkeletonRows } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  type Plan,
  type ShoppingExtra,
  type ShoppingItem,
  type ShoppingList,
  useCurrentPlan,
  useShoppingExtra,
  useShoppingExtras,
  useShoppingList,
  useStockShopping,
  useTickShoppingItem,
} from "@/lib/api/hooks";
import { dateRange } from "@/lib/dates";
import { formatGrams, formatMoney } from "@/lib/format";
import { EmptyState } from "@/components/empty-state";
import { foodName } from "@/lib/food-name";

/** Supermarket-aisle names for USDA food groups. */
const AISLE: Record<string, string> = {
  "Baked Products": "Bakery",
  "Beef Products": "Meat",
  Beverages: "Drinks",
  "Breakfast Cereals": "Cereals",
  "Cereal Grains and Pasta": "Grains & pasta",
  "Dairy and Egg Products": "Dairy & eggs",
  "Fats and Oils": "Oils & fats",
  "Finfish and Shellfish Products": "Fish & seafood",
  "Fruits and Fruit Juices": "Fruit",
  "Lamb, Veal, and Game Products": "Meat",
  "Legumes and Legume Products": "Beans, pulses & tofu",
  "Nut and Seed Products": "Nuts & seeds",
  "Pork Products": "Meat",
  "Poultry Products": "Meat",
  "Sausages and Luncheon Meats": "Meat",
  "Soups, Sauces, and Gravies": "Sauces & stock",
  "Spices and Herbs": "Herbs & spices",
  Sweets: "Baking & sweet things",
  "Vegetables and Vegetable Products": "Vegetables",
};

export function aisle(category: string | null): string {
  if (!category) return "Other";
  return AISLE[category] ?? category;
}

/** Lines grouped by aisle, groups in the order the API sorted the lines. */
export function groupByAisle(items: ShoppingItem[]): [string, ShoppingItem[]][] {
  const groups = new Map<string, ShoppingItem[]>();
  for (const item of items) {
    const key = aisle(item.category);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()];
}

type Tick = ReturnType<typeof useTickShoppingItem>;

function ItemRow({
  item,
  tick,
  currency,
}: {
  item: ShoppingItem;
  tick: Tick;
  currency: ShoppingList["currency"];
}) {
  const id = `shop-${item.food_id}`;
  const { name, detail } = foodName(item.name);
  const amount = item.staple
    ? detail
    : [formatGrams(item.grams), item.approx_units, detail].filter(Boolean).join(" · ");
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <Checkbox
        id={id}
        checked={item.checked}
        aria-describedby={amount ? `${id}-amount` : undefined}
        onCheckedChange={(checked) => tick.mutate({ item, checked })}
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Label
          htmlFor={id}
          className={cn(
            "leading-snug font-normal decoration-muted-foreground/70 motion-safe:transition-colors motion-safe:duration-300",
            item.checked && "text-muted-foreground line-through",
          )}
        >
          {name}
        </Label>
        {amount ? (
          <span id={`${id}-amount`} className="text-xs text-muted-foreground">
            {amount}
            {item.stocked ? " · in your pantry" : ""}
          </span>
        ) : null}
      </div>
      {item.staple ? null : (
        <span className="text-sm text-muted-foreground tabular-nums">
          {formatMoney(item.cost_minor, currency)}
        </span>
      )}
    </li>
  );
}

function Total({ list }: { list: ShoppingList }) {
  const budget = list.budget_minor;
  const over = budget !== null && list.total_minor > budget;
  return (
    <div className="flex items-end justify-between gap-3 rounded-lg bg-muted/60 p-3">
      <div className="flex flex-col">
        <span className="text-xs text-muted-foreground">Estimated total</span>
        <span className="text-2xl font-semibold tabular-nums">
          ≈ {formatMoney(list.total_minor, list.currency)}
        </span>
      </div>
      <div className="flex flex-col items-end text-xs">
        {budget === null ? (
          <span className="text-muted-foreground">No budget set</span>
        ) : over ? (
          <span className="flex items-center gap-1 text-destructive">
            <TriangleAlertIcon aria-hidden className="size-3" />
            {formatMoney(list.total_minor - budget, list.currency)} over your{" "}
            {formatMoney(budget, list.currency)} budget
          </span>
        ) : (
          <span className="text-muted-foreground">Budget {formatMoney(budget, list.currency)}</span>
        )}
      </div>
    </div>
  );
}

function ListView({ plan }: { plan: Plan }) {
  const { data: list, isPending, error, refetch } = useShoppingList(plan.id);
  const tick = useTickShoppingItem(plan.id);
  const stock = useStockShopping(plan.id);
  const { data: extras } = useShoppingExtras();
  const [hideTicked, setHideTicked] = useState(false);

  if (isPending) {
    return (
      <div className="flex flex-col gap-3" aria-busy>
        <Skeleton className="h-16" />
        <SkeletonRows count={6} />
      </div>
    );
  }
  if (error && !list) return <ErrorAlert error={error} onRetry={() => void refetch()} />;

  const toBuy = list.items.filter((i) => !i.staple);
  const staples = list.items.filter((i) => i.staple);
  const ticked = toBuy.filter((i) => i.checked).length;
  const toStock = toBuy.filter((i) => i.checked && !i.stocked).length;
  const shown = hideTicked ? toBuy.filter((i) => !i.checked) : toBuy;

  return (
    <div className="flex flex-col gap-5">
      <Total list={list} />
      {toBuy.length ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground" aria-live="polite">
              {ticked} of {toBuy.length} ticked
            </p>
            <div className="flex items-center gap-2">
              <Switch id="hide-ticked" checked={hideTicked} onCheckedChange={setHideTicked} />
              <Label htmlFor="hide-ticked" className="text-xs font-normal">
                Hide ticked
              </Label>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {toStock ? (
              <Button
                size="sm"
                disabled={stock.isPending}
                onClick={() =>
                  stock.mutate(undefined, {
                    onSuccess: (added) =>
                      toast.success(
                        `Moved ${added.length} ${added.length === 1 ? "item" : "items"} to your pantry`,
                      ),
                  })
                }
              >
                <PackageCheckIcon aria-hidden />
                Move {toStock} ticked to pantry
              </Button>
            ) : null}
            <ShareButton list={list} extras={extras ?? []} />
          </div>
          <ErrorAlert error={stock.error} />
        </div>
      ) : (
        <p className="py-4 text-center text-sm text-muted-foreground">
          Nothing to buy: your pantry covers this plan.
        </p>
      )}
      {groupByAisle(shown).map(([name, items], i) => (
        <section key={name} aria-labelledby={`aisle-${i}`} className="flex flex-col gap-2">
          <h2 id={`aisle-${i}`} className="text-sm font-semibold">
            {name}
          </h2>
          <ul className="flex flex-col divide-y rounded-lg border">
            {items.map((item) => (
              <ItemRow key={item.food_id} item={item} tick={tick} currency={list.currency} />
            ))}
          </ul>
        </section>
      ))}
      {staples.length ? (
        <section aria-labelledby="staples" className="flex flex-col gap-2">
          <h2 id="staples" className="text-sm font-semibold">
            Check you have
          </h2>
          <p className="text-xs text-muted-foreground">
            Store-cupboard items the recipes use a little of.
          </p>
          <ul className="flex flex-col divide-y rounded-lg border">
            {staples.map((item) => (
              <ItemRow key={item.food_id} item={item} tick={tick} currency={list.currency} />
            ))}
          </ul>
        </section>
      ) : null}
      <Extras />
      <PriceNote>Amounts cover the whole plan after what&apos;s in your pantry.</PriceNote>
    </div>
  );
}

/** The list as plain text, by aisle, for messaging apps or notes. */
export function listText(list: ShoppingList, extras: ShoppingExtra[]): string {
  const lines: string[] = [];
  for (const [name, items] of groupByAisle(list.items.filter((i) => !i.staple && !i.checked))) {
    lines.push(`${name}:`);
    for (const i of items) {
      lines.push(`- ${i.name}${i.approx_units ? ` (${i.approx_units})` : ` (${formatGrams(i.grams)})`}`);
    }
  }
  const mine = extras.filter((e) => !e.checked);
  if (mine.length) {
    lines.push("Also:");
    for (const e of mine) lines.push(`- ${e.name}`);
  }
  return lines.join("\n");
}

function ShareButton({ list, extras }: { list: ShoppingList; extras: ShoppingExtra[] }) {
  async function share() {
    const text = listText(list, extras);
    try {
      if (navigator.share) {
        await navigator.share({ title: "Shopping list", text });
        return;
      }
      await navigator.clipboard.writeText(text);
      toast.success("Shopping list copied");
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return; // closed the share sheet
      toast.error("Couldn't share the list");
    }
  }
  return (
    <Button size="sm" variant="outline" onClick={() => void share()}>
      <ShareIcon aria-hidden />
      Share
    </Button>
  );
}

/** Things you want that no recipe needs; kept until you clear them. */
function Extras() {
  const { data: extras } = useShoppingExtras();
  const change = useShoppingExtra();
  const [name, setName] = useState("");
  const ticked = (extras ?? []).filter((e) => e.checked).length;
  return (
    <section aria-labelledby="extras" className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 id="extras" className="text-sm font-semibold">
          Your items
        </h2>
        {ticked ? (
          <Button size="sm" variant="ghost" onClick={() => change.mutate({ kind: "clear" })}>
            Clear {ticked} ticked
          </Button>
        ) : null}
      </div>
      {extras?.length ? (
        <ul className="flex flex-col divide-y rounded-lg border">
          {extras.map((e) => (
            <li key={e.id} className="flex items-center gap-3 px-3 py-1.5">
              <Checkbox
                id={`extra-${e.id}`}
                checked={e.checked}
                onCheckedChange={(checked) =>
                  change.mutate({ kind: "tick", id: e.id, checked: checked === true })
                }
              />
              <Label
                htmlFor={`extra-${e.id}`}
                className={cn(
                  "flex-1 font-normal",
                  e.checked && "text-muted-foreground line-through",
                )}
              >
                {e.name}
              </Label>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Remove ${e.name}`}
                onClick={() => change.mutate({ kind: "delete", id: e.id })}
              >
                <XIcon />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      <form
        className="flex gap-2"
        onSubmit={(ev) => {
          ev.preventDefault();
          if (!name.trim()) return;
          change.mutate({ kind: "add", name: name.trim() }, { onSuccess: () => setName("") });
        }}
      >
        <Input
          value={name}
          onChange={(ev) => setName(ev.target.value)}
          placeholder="Add something, e.g. bin bags"
          aria-label="Add your own item"
          maxLength={120}
        />
        <Button type="submit" variant="outline" disabled={!name.trim() || change.isPending}>
          Add
        </Button>
      </form>
    </section>
  );
}

/** What to buy for the current plan, by aisle, with tick-as-you-shop boxes. */
export function ShoppingPage() {
  const { data: plan, isPending, error, refetch } = useCurrentPlan();
  const first = plan?.days[0]?.date ?? plan?.start;
  const last = plan?.days.at(-1)?.date ?? plan?.start;

  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/plan"
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2 self-start")}
      >
        <ArrowLeftIcon aria-hidden />
        Plan
      </Link>
      <div className="flex flex-col">
        <h1 className="text-2xl font-semibold tracking-tight">Shopping list</h1>
        {first && last ? (
          <p className="text-sm text-muted-foreground">For {dateRange(first, last)}</p>
        ) : null}
      </div>
      {isPending ? (
        <Skeleton className="h-16" />
      ) : error && !plan ? (
        <ErrorAlert error={error} onRetry={() => void refetch()} />
      ) : plan ? (
        <ListView plan={plan} />
      ) : (
        <EmptyState
          art="shopping"
          title="Nothing to buy yet"
          action={
            <Link href="/plan" className={buttonVariants()}>
              Plan my week
            </Link>
          }
        >
          Plan your week and the shopping list appears here.
        </EmptyState>
      )}
    </div>
  );
}
