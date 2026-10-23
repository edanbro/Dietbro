"use client";

import { cn } from "cn";
import {
  ArrowLeftIcon,
  CheckIcon,
  MinusIcon,
  PlusIcon,
  StickyNoteIcon,
  SunIcon,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { ErrorAlert } from "@/components/form-bits";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type Recipe, useRecipe } from "@/lib/api/hooks";
import { parseServings, scaleFactor, steps, stepTimers } from "@/lib/cooking";
import { formatGrams } from "@/lib/format";
import { useWakeLock } from "@/lib/use-wake-lock";

import { RunningTimers, TimerChip, useTimers } from "./timers";

function amount(ing: Recipe["ingredients"][number], factor: number): string {
  if (factor === 1 || ing.grams == null) return ing.measure || "";
  return formatGrams(ing.grams * factor);
}

function CookView({ recipe, initial }: { recipe: Recipe; initial: number }) {
  const [servings, setServings] = useState(initial);
  const [got, setGot] = useState<Set<number>>(new Set());
  const [done, setDone] = useState<Set<number>>(new Set());
  const awake = useWakeLock();
  const timers = useTimers();
  const factor = scaleFactor(servings, recipe.servings);
  const method = steps(recipe.instructions);
  const current = method.findIndex((_, i) => !done.has(i)); // -1: all done
  const toggle = (set: Set<number>, i: number) => {
    const next = new Set(set);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    return next;
  };

  return (
    <article className="flex flex-col gap-5">
      <Link
        href={`/recipes/${recipe.id}`}
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2 self-start")}
      >
        <ArrowLeftIcon aria-hidden />
        Recipe
      </Link>
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-3xl leading-tight font-semibold tracking-tight">
          {recipe.name}
        </h1>
        {method.length ? (
          <div className="flex items-center gap-3">
            <div
              role="progressbar"
              aria-label="Steps done"
              aria-valuemin={0}
              aria-valuemax={method.length}
              aria-valuenow={done.size}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
            >
              <div
                className="h-full rounded-full bg-primary transition-[width] motion-reduce:transition-none"
                style={{ width: `${(done.size / method.length) * 100}%` }}
              />
            </div>
            <span className="text-xs text-muted-foreground tabular-nums">
              {done.size} of {method.length} steps
            </span>
          </div>
        ) : null}
        {recipe.note?.note ? (
          <p
            role="note"
            className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-950 dark:bg-amber-950/40 dark:text-amber-100"
          >
            <StickyNoteIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
            <span>
              <span className="font-medium">Your note:</span> {recipe.note.note}
            </span>
          </p>
        ) : null}
        {awake ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <SunIcon aria-hidden className="size-3.5" />
            Your screen stays on while you cook.
          </p>
        ) : null}
      </header>

      {/* Phones: ingredients, then the method. Wider (a tablet, a phone on its side): side by
          side, the ingredients staying in view while the method scrolls. */}
      <div className="flex flex-col gap-6 md:grid md:grid-cols-[minmax(15rem,2fr)_3fr] md:items-start md:gap-8">
        <section
          aria-labelledby="cook-ingredients"
          className="flex flex-col gap-2 md:sticky md:top-4"
        >
          <div className="flex items-center justify-between gap-2">
            <h2 id="cook-ingredients" className="font-heading text-lg font-semibold">
              Ingredients
            </h2>
            <div className="flex items-center gap-1" role="group" aria-label="Servings">
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="Fewer servings"
                disabled={servings <= 0.5}
                onClick={() => setServings(Math.max(0.5, servings - 0.5))}
              >
                <MinusIcon />
              </Button>
              <span className="w-24 text-center text-sm tabular-nums" aria-live="polite">
                {servings} {servings === 1 ? "serving" : "servings"}
              </span>
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="More servings"
                disabled={servings >= 20}
                onClick={() => setServings(Math.min(20, servings + 0.5))}
              >
                <PlusIcon />
              </Button>
            </div>
          </div>
          {factor !== 1 && recipe.ingredients.some((i) => i.grams == null) ? (
            <p className="text-xs text-muted-foreground">
              Amounts without a weight are for {recipe.servings} servings.
            </p>
          ) : null}
          <ul className="flex flex-col divide-y rounded-xl border text-sm">
            {recipe.ingredients.map((ing, i) => (
              <li key={`${ing.name}-${i}`}>
                <label className="flex cursor-pointer items-start gap-3 px-3 py-2.5">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 shrink-0 accent-primary"
                    checked={got.has(i)}
                    onChange={() => setGot(toggle(got, i))}
                  />
                  <span
                    className={cn(
                      "flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2",
                      got.has(i) && "line-through opacity-50",
                    )}
                  >
                    <span className="font-medium">{ing.name}</span>
                    <span className="text-muted-foreground tabular-nums">
                      {amount(ing, factor)}
                    </span>
                  </span>
                  {ing.in_pantry ? (
                    <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100">
                      In your pantry
                    </span>
                  ) : null}
                </label>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="cook-method" className="flex flex-col gap-2">
          <h2 id="cook-method" className="font-heading text-lg font-semibold">
            Method
          </h2>
          <ol className="flex flex-col gap-2">
            {method.map((step, i) => {
              const finished = done.has(i);
              const now = i === current;
              return (
                <li
                  key={i}
                  aria-current={now ? "step" : undefined}
                  className={cn(
                    "flex gap-3 rounded-2xl p-3 transition-colors motion-reduce:transition-none",
                    now && "bg-primary/5 ring-1 ring-primary/30",
                  )}
                >
                  <button
                    type="button"
                    aria-pressed={finished}
                    aria-label={`Step ${i + 1} done`}
                    onClick={() => setDone(toggle(done, i))}
                    className={cn(
                      "grid size-9 shrink-0 place-items-center rounded-full border text-sm font-semibold tabular-nums",
                      now && "border-primary text-primary",
                      finished && "border-primary bg-primary text-primary-foreground",
                    )}
                  >
                    {finished ? <CheckIcon aria-hidden className="size-4" /> : i + 1}
                  </button>
                  <div className="flex min-w-0 flex-1 flex-col gap-2 pt-1">
                    <p
                      className={cn(
                        "leading-relaxed",
                        now ? "text-lg" : "text-base",
                        finished && "text-muted-foreground line-through",
                      )}
                    >
                      {step}
                    </p>
                    {finished ? null : (
                      <div className="flex flex-wrap gap-2">
                        {stepTimers(step).map((t, j) => (
                          <TimerChip key={`${i}-${j}`} id={`${i}-${j}`} timer={t} timers={timers} />
                        ))}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          {method.length && current === -1 ? (
            <p className="rounded-xl bg-muted p-3 text-sm font-medium" role="status">
              All done. Enjoy!
            </p>
          ) : null}
        </section>
      </div>
      <RunningTimers timers={timers} />
    </article>
  );
}

/** Step-by-step cooking: scaled ingredients, tickable steps, timers, screen kept on. */
export function CookMode({ id }: { id: number }) {
  const { data: recipe, isPending, error, refetch } = useRecipe(id);
  const asked = parseServings(useSearchParams().get("servings"));
  if (isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy>
        <Skeleton className="h-8 w-3/4" />
        <Skeleton className="h-48" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (error) return <ErrorAlert error={error} onRetry={() => void refetch()} />;
  return <CookView recipe={recipe} initial={asked ?? recipe.servings ?? 2} />;
}
