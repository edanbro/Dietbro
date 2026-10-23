"use client";

import { cn } from "cn";
import { ArrowLeftIcon, CheckIcon, SunIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorAlert } from "@/components/form-bits";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type Recipe, useRecipes } from "@/lib/api/hooks";
import { scaleFactor, steps } from "@/lib/cooking";
import { foodName } from "@/lib/food-name";
import { formatGrams } from "@/lib/format";
import { parsePrep, type PrepEvent, schedule, totalTime } from "@/lib/prep";
import { useWakeLock } from "@/lib/use-wake-lock";

import { RunningTimers, TimerChip, useTimers } from "./timers";

// One colour per recipe, so its steps can be followed down the timeline.
const TINTS = ["bg-primary/15", "bg-amber-500/20", "bg-sky-500/20", "bg-violet-500/20"];

/** 0 -> "Start", 300 -> "5 min", 3900 -> "1 h 5 min". */
export function offset(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes === 0) return "Start";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h} h${m ? ` ${m} min` : ""}` : `${m} min`;
}

type Line = { key: string; name: string; amount: string; recipes: string[] };

/** What to get out: weighed ingredients added up across the recipes (by food), the rest as
 * written, each scaled to its recipe's servings. */
export function gatherIngredients(cooking: { recipe: Recipe; servings: number }[]): Line[] {
  const byFood = new Map<number, { name: string; grams: number; recipes: Set<string> }>();
  const other: Line[] = [];
  for (const { recipe, servings } of cooking) {
    const factor = scaleFactor(servings, recipe.servings);
    for (const [i, ing] of recipe.ingredients.entries()) {
      if (ing.food_id !== null && ing.grams !== null) {
        const seen = byFood.get(ing.food_id);
        if (seen) {
          seen.grams += ing.grams * factor;
          seen.recipes.add(recipe.name);
        } else {
          byFood.set(ing.food_id, {
            name: ing.name,
            grams: ing.grams * factor,
            recipes: new Set([recipe.name]),
          });
        }
      } else {
        other.push({
          key: `${recipe.id}-${i}`,
          name: ing.name,
          amount: ing.measure,
          recipes: [recipe.name],
        });
      }
    }
  }
  const weighed: Line[] = [...byFood].map(([id, v]) => ({
    key: `food-${id}`,
    name: v.name,
    amount: formatGrams(v.grams),
    recipes: [...v.recipes],
  }));
  return [...weighed, ...other].sort((a, b) => a.name.localeCompare(b.name));
}

function Timeline({ events, tint }: { events: PrepEvent[]; tint: (id: number) => string }) {
  const timers = useTimers();
  const [done, setDone] = useState<ReadonlySet<string>>(new Set());
  const key = (e: PrepEvent) => `${e.recipeId}-${e.index}`;
  const current = events.find((e) => !done.has(key(e)));
  const names = new Map(events.map((e) => [key(e), e.recipe]));
  return (
    <section aria-labelledby="prep-steps" className="flex flex-col gap-2">
      <h2 id="prep-steps" className="font-heading text-lg font-semibold">
        Steps
      </h2>
      <ol className="flex flex-col gap-2">
        {events.map((e) => {
          const id = key(e);
          const finished = done.has(id);
          const now = e === current;
          return (
            <li
              key={id}
              aria-current={now ? "step" : undefined}
              className={cn(
                "flex gap-3 rounded-2xl p-3",
                now && "bg-primary/5 ring-1 ring-primary/30",
              )}
            >
              <span className="w-14 shrink-0 pt-1.5 text-xs text-muted-foreground tabular-nums">
                {offset(e.start)}
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span
                  className={cn(
                    "self-start rounded-full px-2 py-0.5 text-xs font-medium",
                    tint(e.recipeId),
                  )}
                >
                  {e.recipe} · step {e.index + 1}
                </span>
                <p
                  className={cn(
                    "leading-relaxed",
                    now ? "text-lg" : "text-base",
                    finished && "text-muted-foreground line-through",
                  )}
                >
                  {e.step}
                </p>
                {e.timer && !finished ? (
                  <div className="flex">
                    <TimerChip id={id} timer={e.timer} timers={timers} />
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                aria-pressed={finished}
                aria-label={`${e.recipe} step ${e.index + 1} done`}
                onClick={() =>
                  setDone((all) => {
                    const next = new Set(all);
                    if (next.has(id)) next.delete(id);
                    else next.add(id);
                    return next;
                  })
                }
                className={cn(
                  "grid size-9 shrink-0 place-items-center rounded-full border",
                  finished && "border-primary bg-primary text-primary-foreground",
                )}
              >
                {finished ? <CheckIcon aria-hidden className="size-4" /> : null}
              </button>
            </li>
          );
        })}
      </ol>
      {current === undefined ? (
        <p className="rounded-xl bg-muted p-3 text-sm font-medium" role="status">
          All done. Into the fridge with it!
        </p>
      ) : null}
      <RunningTimers timers={timers} name={(id) => names.get(id)} />
    </section>
  );
}

/**
 * Cooking several recipes at once (?r=<id>x<servings>,...): what to get out, then one timeline
 * with the steps interleaved so long waits fill with other work (lib/prep.ts), timers side by
 * side, the screen kept on.
 */
export function MealPrep() {
  const wanted = parsePrep(useSearchParams().get("r"));
  const results = useRecipes(wanted.map((w) => w.id));
  const awake = useWakeLock();
  if (!wanted.length) {
    return (
      <EmptyState
        art="plan"
        title="Nothing to prep"
        action={
          <Link href="/plan" className={buttonVariants()}>
            Pick meals on your plan
          </Link>
        }
      >
        Choose a few of this week&apos;s meals with Meal prep on the plan.
      </EmptyState>
    );
  }
  const failed = results.find((r) => r.error);
  if (failed?.error)
    return <ErrorAlert error={failed.error} onRetry={() => void failed.refetch()} />;
  if (results.some((r) => r.isPending)) {
    return (
      <div className="flex flex-col gap-3" aria-busy>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-48" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  const cooking = wanted.flatMap((w, i) => {
    const recipe = results[i]?.data;
    return recipe ? [{ recipe, servings: w.servings }] : [];
  });
  const tints = new Map(cooking.map(({ recipe }, i) => [recipe.id, TINTS[i % TINTS.length]!]));
  const events = schedule(
    cooking.map(({ recipe }) => ({
      id: recipe.id,
      name: recipe.name,
      steps: steps(recipe.instructions),
    })),
  );
  const lines = gatherIngredients(cooking);

  return (
    <article className="flex flex-col gap-5">
      <Link
        href="/plan"
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2 self-start")}
      >
        <ArrowLeftIcon aria-hidden />
        Plan
      </Link>
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-3xl font-semibold tracking-tight">Meal prep</h1>
        <ul className="flex flex-wrap gap-2" aria-label="Cooking">
          {cooking.map(({ recipe, servings }) => (
            <li
              key={recipe.id}
              className={cn("rounded-full px-2.5 py-1 text-sm", tints.get(recipe.id))}
            >
              {recipe.name} · {servings} {servings === 1 ? "serving" : "servings"}
            </li>
          ))}
        </ul>
        <p className="text-sm text-muted-foreground">
          About {offset(totalTime(events))} start to finish, for one cook.
        </p>
        {awake ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <SunIcon aria-hidden className="size-3.5" />
            Your screen stays on while you cook.
          </p>
        ) : null}
      </header>

      <div className="flex flex-col gap-6 md:grid md:grid-cols-[minmax(15rem,2fr)_3fr] md:items-start md:gap-8">
        <section aria-labelledby="prep-get-out" className="flex flex-col gap-2 md:sticky md:top-4">
          <h2 id="prep-get-out" className="font-heading text-lg font-semibold">
            Get out
          </h2>
          <ul className="flex flex-col divide-y rounded-xl border text-sm">
            {lines.map((l) => (
              <li key={l.key} className="flex flex-wrap items-baseline gap-x-2 px-3 py-2">
                <span className="font-medium">{foodName(l.name).name}</span>
                <span className="text-muted-foreground tabular-nums">{l.amount}</span>
                {cooking.length > 1 ? (
                  <span className="w-full text-xs text-muted-foreground">
                    {l.recipes.join(", ")}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
        <Timeline events={events} tint={(id) => tints.get(id) ?? TINTS[0]!} />
      </div>
    </article>
  );
}
