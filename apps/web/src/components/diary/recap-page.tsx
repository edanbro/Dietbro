"use client";

import { ChevronLeftIcon, ChevronRightIcon, TrendingUpIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { EmptyState } from "@/components/empty-state";
import { ErrorAlert } from "@/components/form-bits";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type Recap, useRecap, useUnits } from "@/lib/api/hooks";
import { addDays, dateRange, localISODate } from "@/lib/dates";
import { foodName } from "@/lib/food-name";
import { bodyUnit, bodyWeight, formatBodyWeight } from "@/lib/units";
import { formatMoney, formatNumber } from "@/lib/format";

import { PriceWatch } from "./price-watch";
import { SpendingSection } from "./spending";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-1 rounded-2xl bg-muted/60 p-4">
      <h2 className="text-xs font-medium text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

function Big({ children }: { children: React.ReactNode }) {
  return <p className="font-heading text-2xl font-semibold tabular-nums">{children}</p>;
}

function Small({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function days(n: number): string {
  return `${n} ${n === 1 ? "day" : "days"}`;
}

function Summary({ recap }: { recap: Recap }) {
  const money = (minor: number) => formatMoney(minor, recap.currency);
  const units = useUnits();
  const band =
    recap.kcal_min != null && recap.kcal_max != null
      ? `${formatNumber(recap.kcal_min)}–${formatNumber(recap.kcal_max)} kcal`
      : null;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {recap.planned_meals || recap.eaten_meals || recap.skipped_meals || recap.off_plan ? (
        <Card title="Meals">
          <Big>
            {recap.planned_meals
              ? `${recap.eaten_meals} of ${recap.planned_meals}`
              : `${recap.eaten_meals}`}
          </Big>
          <Small>
            planned meals eaten
            {recap.skipped_meals ? ` · ${recap.skipped_meals} skipped` : ""}
            {recap.off_plan ? ` · ${recap.off_plan} off the plan` : ""}
          </Small>
        </Card>
      ) : null}
      {recap.avg_kcal != null ? (
        <Card title="Calories">
          <Big>{formatNumber(recap.avg_kcal)} kcal</Big>
          <Small>
            a day on average; {recap.on_target_days} of {days(recap.logged_days)} logged
            {band ? ` within ${band}` : ""}
          </Small>
        </Card>
      ) : null}
      {recap.protein_g_min != null && recap.protein_days != null && recap.logged_days ? (
        <Card title="Protein">
          <Big>
            {recap.protein_days} of {days(recap.logged_days)}
          </Big>
          <Small>reached {formatNumber(recap.protein_g_min)} g</Small>
        </Card>
      ) : null}
      {recap.spent_minor || recap.planned_cost_minor ? (
        <Card title="Spending">
          <Big>{money(recap.spent_minor)}</Big>
          <Small>
            {recap.budget_minor ? `of a ${money(recap.budget_minor)} budget` : "spent"}
            {recap.planned_cost_minor
              ? `; the plan expected ${money(recap.planned_cost_minor)}`
              : ""}
          </Small>
        </Card>
      ) : null}
      {recap.weight_change_kg != null ? (
        <Card title="Weight">
          <Big>
            {recap.weight_change_kg > 0 ? "+" : ""}
            {bodyWeight(recap.weight_change_kg, units).toFixed(1)} {bodyUnit(units)}
          </Big>
          <Small>
            {recap.weight_kg != null ? `to ${formatBodyWeight(recap.weight_kg, units)}, ` : ""}
            first to last weigh-in
          </Small>
        </Card>
      ) : recap.weight_kg != null ? (
        // One weigh-in has no change to show, but it's why this week isn't empty.
        <Card title="Weight">
          <Big>{formatBodyWeight(recap.weight_kg, units)}</Big>
          <Small>your only weigh-in this week</Small>
        </Card>
      ) : null}
      {recap.top_recipes.length ? (
        <Card title="Eaten most">
          <ul className="flex flex-col gap-1 text-sm">
            {recap.top_recipes.map((t) => (
              <li key={t.recipe.id} className="flex justify-between gap-2">
                <Link
                  href={`/recipes/${t.recipe.id}`}
                  className="underline-offset-4 hover:underline"
                >
                  {t.recipe.name}
                </Link>
                <span className="text-muted-foreground tabular-nums">×{t.times}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      {recap.price_rises.length ? (
        <Card title="Prices up">
          <ul className="flex flex-col gap-1 text-sm">
            {recap.price_rises.map((p) => (
              <li key={p.name} className="flex justify-between gap-2">
                <span>{foodName(p.name).name}</span>
                <span className="flex items-center gap-1 text-warning tabular-nums">
                  <TrendingUpIcon aria-hidden className="size-3.5" />+{p.change_pct}%
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

/**
 * A week looked back on: meals eaten, energy and protein, spending, weight, favourites and
 * prices that went up. ?week= picks the week (any of its days); the last full week otherwise.
 */
export function RecapPage() {
  const router = useRouter();
  const week = useSearchParams().get("week") ?? undefined;
  const recap = useRecap(week);
  const today = localISODate();
  const go = (start: string) => router.replace(`/recap?week=${start}`);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-3xl font-semibold">Week in review</h1>
      {recap.isPending ? (
        <Skeleton className="h-64" />
      ) : recap.error ? (
        <ErrorAlert error={recap.error} onRetry={() => void recap.refetch()} />
      ) : (
        <>
          <nav aria-label="Week" className="flex items-center justify-between gap-2">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Week before"
              onClick={() => go(addDays(recap.data.week_start, -7))}
            >
              <ChevronLeftIcon />
            </Button>
            <p className="text-sm font-medium" aria-live="polite">
              {dateRange(recap.data.week_start, recap.data.week_end)}
            </p>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Week after"
              disabled={addDays(recap.data.week_start, 7) > today}
              onClick={() => go(addDays(recap.data.week_start, 7))}
            >
              <ChevronRightIcon />
            </Button>
          </nav>
          {recap.data.empty ? (
            <EmptyState
              art="diary"
              title="Nothing that week"
              action={
                <Link href="/diary" className={buttonVariants({ variant: "outline" })}>
                  Open the diary
                </Link>
              }
            >
              Mark meals eaten, add receipts or weigh in, and next week&apos;s review fills itself.
            </EmptyState>
          ) : (
            <Summary recap={recap.data} />
          )}
        </>
      )}
      <SpendingSection />
      <PriceWatch />
    </div>
  );
}
