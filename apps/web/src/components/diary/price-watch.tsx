"use client";

import { cn } from "cn";
import { TrendingDownIcon, TrendingUpIcon } from "lucide-react";
import Link from "next/link";

import { ErrorAlert } from "@/components/form-bits";
import { Skeleton } from "@/components/ui/skeleton";
import { type PriceItem, type Prices, usePrices, useUnits } from "@/lib/api/hooks";
import { shortDate } from "@/lib/dates";
import { foodName } from "@/lib/food-name";
import { formatMoney } from "@/lib/format";
import { perWeight, type Units } from "@/lib/units";

const W = 72;
const H = 24;
const SHOWN = 8;

/** The item's prices over time as a tiny line, the latest one marked. */
function Sparkline({ item, rise }: { item: PriceItem; rise: boolean }) {
  const prices = item.history.map((p) => p.per_kg_minor);
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);
  const x = (i: number) => (prices.length === 1 ? W / 2 : 2 + (i * (W - 4)) / (prices.length - 1));
  const y = (p: number) => (hi === lo ? H / 2 : 3 + (1 - (p - lo) / (hi - lo)) * (H - 6));
  const points = prices.map((p, i) => `${x(i)},${y(p)}`).join(" ");
  const last = prices.length - 1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden className="shrink-0">
      <polyline
        points={points}
        fill="none"
        strokeWidth={1.5}
        strokeLinejoin="round"
        className="stroke-muted-foreground/60"
      />
      <circle
        cx={x(last)}
        cy={y(prices[last]!)}
        r={2.5}
        className={rise ? "fill-amber-500" : "fill-primary"}
      />
    </svg>
  );
}

function Row({
  item,
  currency,
  units,
}: {
  item: PriceItem;
  currency: Prices["currency"];
  units: Units;
}) {
  // Prices per kg as the shopper compares them: "€2.10/kg", or "$0.95/lb" in the US.
  const price = (perKg: number) => formatMoney(perWeight(perKg, units).minor, currency);
  const unit = perWeight(0, units).unit;
  const { name, detail } = foodName(item.name);
  const change = item.change_pct;
  return (
    <li className="flex flex-col gap-1 py-2.5">
      <div className="flex items-center gap-3">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate font-medium">
            {name}
            {detail ? <span className="font-normal text-muted-foreground"> · {detail}</span> : null}
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {price(item.latest_minor)}/{unit}, usually {price(item.usual_minor)}
          </span>
        </div>
        <Sparkline item={item} rise={item.rise} />
        <span
          className={cn(
            "flex w-16 items-center justify-end gap-1 text-sm tabular-nums",
            item.rise
              ? "font-medium text-amber-700 dark:text-amber-400"
              : change < 0
                ? "text-emerald-700 dark:text-emerald-400"
                : "text-muted-foreground",
          )}
        >
          {item.rise ? <TrendingUpIcon aria-hidden className="size-3.5" /> : null}
          {change < 0 ? <TrendingDownIcon aria-hidden className="size-3.5" /> : null}
          {change > 0 ? "+" : ""}
          {change}%
        </span>
      </div>
      {item.cheaper ? (
        <p className="text-xs text-muted-foreground">
          Cheaper: {item.cheaper.label} at {price(item.cheaper.per_kg_minor)}/{unit} (last bought{" "}
          {shortDate(item.cheaper.last_bought)})
        </p>
      ) : null}
    </li>
  );
}

/**
 * What you pay for the foods you buy again and again, from your own receipts: rises against
 * the usual price first, each with a cheaper product you've bought for it when there is one.
 */
export function PriceWatch() {
  const prices = usePrices();
  const units = useUnits();
  return (
    <section aria-labelledby="price-watch" className="flex flex-col gap-2">
      <h2 id="price-watch" className="text-xl font-semibold">
        Price watch
      </h2>
      {prices.isPending ? (
        <Skeleton className="h-24" />
      ) : prices.error ? (
        <ErrorAlert error={prices.error} onRetry={() => void prices.refetch()} />
      ) : prices.data.items.length ? (
        <>
          <ul className="flex flex-col divide-y" aria-label="Prices you've paid">
            {prices.data.items.slice(0, SHOWN).map((item) => (
              <Row
                key={item.food_id}
                item={item}
                currency={prices.data.currency}
                units={units}
              />
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            Per {units === "us" ? "lb" : "kg"}, from receipts with the size printed, over the last
            6 months.
          </p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Once you&apos;ve bought something twice, with the receipt added, its price shows up here,
          with any rise and a cheaper option you&apos;ve bought before.{" "}
          <Link href="/pantry/receipts" className="text-foreground underline underline-offset-4">
            Add a receipt
          </Link>
        </p>
      )}
    </section>
  );
}
