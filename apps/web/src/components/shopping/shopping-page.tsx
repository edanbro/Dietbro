"use client";

import { cn } from "cn";
import { ArrowLeftIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";

import { ErrorAlert } from "@/components/form-bits";
import { buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type Plan,
  type ShoppingItem,
  type ShoppingList,
  useCurrentPlan,
  useShoppingList,
  useTickShoppingItem,
} from "@/lib/api/hooks";
import { dateRange } from "@/lib/dates";
import { formatGrams, formatMoney } from "@/lib/format";

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
  const amount = item.staple
    ? null
    : [formatGrams(item.grams), item.approx_units].filter(Boolean).join(" · ");
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
            "leading-snug font-normal",
            item.checked && "text-muted-foreground line-through",
          )}
        >
          {item.name}
        </Label>
        {amount ? (
          <span id={`${id}-amount`} className="text-xs text-muted-foreground">
            {amount}
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
  const { data: list, isPending, error } = useShoppingList(plan.id);
  const tick = useTickShoppingItem(plan.id);

  if (isPending) {
    return (
      <div className="flex flex-col gap-2" aria-busy>
        <Skeleton className="h-16" />
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
      </div>
    );
  }
  if (error) return <ErrorAlert error={error} />;

  const toBuy = list.items.filter((i) => !i.staple);
  const staples = list.items.filter((i) => i.staple);
  const ticked = toBuy.filter((i) => i.checked).length;

  return (
    <div className="flex flex-col gap-5">
      <Total list={list} />
      {toBuy.length ? (
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {ticked} of {toBuy.length} ticked
        </p>
      ) : (
        <p className="py-4 text-center text-sm text-muted-foreground">
          Nothing to buy: your pantry covers this plan.
        </p>
      )}
      {groupByAisle(toBuy).map(([name, items], i) => (
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
      <p className="text-xs text-muted-foreground">
        Amounts cover the whole plan after what&apos;s in your pantry. Prices are estimates from
        typical UK supermarket prices.
      </p>
    </div>
  );
}

/** What to buy for the current plan, by aisle, with tick-as-you-shop boxes. */
export function ShoppingPage() {
  const { data: plan, isPending, error } = useCurrentPlan();
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
      ) : error ? (
        <ErrorAlert error={error} />
      ) : plan ? (
        <ListView plan={plan} />
      ) : (
        <div className="flex flex-col items-center gap-3 py-8 text-center">
          <p className="text-sm text-muted-foreground">
            No plan yet. Plan your week and the shopping list appears here.
          </p>
          <Link href="/plan" className={buttonVariants()}>
            Plan my week
          </Link>
        </div>
      )}
    </div>
  );
}
