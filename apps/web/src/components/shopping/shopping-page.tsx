"use client";

import { cn } from "cn";
import {
  ArrowLeftIcon,
  PackageCheckIcon,
  PlusIcon,
  PrinterIcon,
  ShareIcon,
  TriangleAlertIcon,
  UsersIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { PriceNote } from "@/components/price-note";
import { ShareLinkButton } from "@/components/share-link-button";
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
  useShoppingUsuals,
  useShoppingList,
  useUnits,
  useStockShopping,
  useTickShoppingItem,
} from "@/lib/api/hooks";
import { dateRange, weekday } from "@/lib/dates";
import { formatMoney } from "@/lib/format";
import { EmptyState } from "@/components/empty-state";
import { aisle } from "@/lib/aisles";
import { foodName } from "@/lib/food-name";
import { formatWeight, type Units } from "@/lib/units";

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

/** "For Chilli (Mon, Thu) and Fish pie (Wed)", "For Chilli (Mon), Fish pie (Wed) +2". */
export function usedFor(used: ShoppingItem["used_in"], shown = 2): string | null {
  if (!used?.length) return null;
  const parts = used.slice(0, shown).map((u) => `${u.name} (${u.dates.map(weekday).join(", ")})`);
  if (used.length > shown) return `For ${parts.join(", ")} +${used.length - shown}`;
  const last = parts.pop()!;
  return `For ${parts.length ? `${parts.join(", ")} and ${last}` : last}`;
}

function ItemRow({
  item,
  tick,
  currency,
  units,
}: {
  item: ShoppingItem;
  tick: Tick;
  currency: ShoppingList["currency"];
  units: Units;
}) {
  const id = `shop-${item.food_id}`;
  const { name, detail } = foodName(item.name);
  const amount = item.staple
    ? detail
    : [formatWeight(item.grams, units), item.approx_units, detail].filter(Boolean).join(" · ");
  const used = usedFor(item.used_in);
  const described = [amount ? `${id}-amount` : null, used ? `${id}-used` : null].filter(Boolean);
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <Checkbox
        id={id}
        checked={item.checked}
        aria-describedby={described.length ? described.join(" ") : undefined}
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
        {used ? (
          <span id={`${id}-used`} className="line-clamp-2 text-xs text-muted-foreground">
            {used}
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
        <span className="text-xs text-muted-foreground">
          Estimated total{list.household > 1 ? `, for ${list.household} people` : ""}
        </span>
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
  const units = useUnits();
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
          <div className="flex flex-wrap items-center justify-between gap-2 print:hidden">
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
          <div className="flex flex-wrap gap-2 print:hidden">
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
            <ShareLinkButton
              target={{ kind: "list", start: plan.start }}
              title="Shopping list"
              label="Shop together"
              icon={UsersIcon}
              reach="can tick things off"
            />
            <ShareButton list={list} extras={extras ?? []} />
            <Button size="sm" variant="outline" onClick={() => window.print()}>
              <PrinterIcon aria-hidden />
              Print
            </Button>
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
              <ItemRow
                key={item.food_id}
                item={item}
                tick={tick}
                currency={list.currency}
                units={units}
              />
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
              <ItemRow
                key={item.food_id}
                item={item}
                tick={tick}
                currency={list.currency}
                units={units}
              />
            ))}
          </ul>
        </section>
      ) : null}
      <Extras listed={list.items.map((i) => i.food_id)} />
      <PriceNote>Amounts cover the whole plan after what&apos;s in your pantry.</PriceNote>
    </div>
  );
}

/** The list as plain text, by aisle, for messaging apps or notes. */
export function listText(
  list: ShoppingList,
  extras: ShoppingExtra[],
  units: Units = "metric",
): string {
  const lines: string[] = [];
  for (const [name, items] of groupByAisle(list.items.filter((i) => !i.staple && !i.checked))) {
    lines.push(`${name}:`);
    for (const i of items) {
      const amount = i.approx_units ?? formatWeight(i.grams, units);
      lines.push(`- ${foodName(i.name).name} (${amount})`);
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
  const units = useUnits();
  async function share() {
    const text = listText(list, extras, units);
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
      Send as text
    </Button>
  );
}

/** Things you want that no recipe needs; kept until you clear them. Offers what the receipts
 * say you buy most weeks (`listed`: foods the plan's list already has). */
function Extras({ listed }: { listed: number[] }) {
  const { data: extras } = useShoppingExtras();
  const { data: usuals } = useShoppingUsuals();
  const change = useShoppingExtra();
  const [name, setName] = useState("");
  const ticked = (extras ?? []).filter((e) => e.checked).length;
  const have = new Set((extras ?? []).map((e) => e.name.toLowerCase()));
  const offered = (usuals ?? [])
    .map((u) => ({ ...u, label: foodName(u.name).name }))
    .filter((u) => !listed.includes(u.food_id) && !have.has(u.label.toLowerCase()));
  return (
    <section
      aria-labelledby="extras"
      className={cn("flex flex-col gap-2", !extras?.length && "print:hidden")}
    >
      <div className="flex items-center justify-between">
        <h2 id="extras" className="text-sm font-semibold">
          Your items
        </h2>
        {ticked ? (
          <Button
            size="sm"
            variant="ghost"
            className="print:hidden"
            onClick={() => change.mutate({ kind: "clear" })}
          >
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
                className="print:hidden"
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
        className="flex gap-2 print:hidden"
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
      {offered.length ? (
        <div className="flex flex-col gap-1.5 print:hidden">
          <h3 id="usuals" className="text-xs text-muted-foreground">
            You often buy
          </h3>
          <ul aria-labelledby="usuals" className="flex flex-wrap gap-1.5">
            {offered.map((u) => (
              <li key={u.food_id}>
                <button
                  type="button"
                  disabled={change.isPending}
                  onClick={() => change.mutate({ kind: "add", name: u.label })}
                  className="inline-flex h-8 items-center gap-1 rounded-full border px-3 text-sm hover:bg-muted"
                  aria-label={`Add ${u.label}`}
                >
                  <PlusIcon aria-hidden className="size-3.5" />
                  {u.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
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
        className={cn(
          buttonVariants({ variant: "ghost", size: "sm" }),
          "-ml-2 self-start print:hidden",
        )}
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
