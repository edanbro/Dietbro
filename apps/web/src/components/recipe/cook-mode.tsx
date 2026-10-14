"use client";

import { cn } from "cn";
import {
  ArrowLeftIcon,
  CheckIcon,
  MinusIcon,
  PauseIcon,
  PlayIcon,
  PlusIcon,
  RotateCcwIcon,
  SunIcon,
  TimerIcon,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type Recipe, useRecipe } from "@/lib/api/hooks";
import { clock, parseServings, scaleFactor, type StepTimer, stepTimers } from "@/lib/cooking";
import { formatGrams } from "@/lib/format";

import { steps } from "./recipe-page";

/**
 * Keeps the screen on while cooking (Screen Wake Lock), taking the lock again when the tab
 * comes back (browsers drop it when hidden). Unsupported browsers: nothing happens.
 */
function useWakeLock(): boolean {
  const [held, setHeld] = useState(false);
  useEffect(() => {
    if (!("wakeLock" in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    let cancelled = false;
    const take = async () => {
      try {
        lock = await navigator.wakeLock.request("screen");
        if (cancelled) {
          void lock.release();
          return;
        }
        setHeld(true);
        lock.addEventListener("release", () => setHeld(false));
      } catch {
        setHeld(false); // denied (battery saver) or not visible
      }
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") void take();
    };
    void take();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      void lock?.release();
    };
  }, []);
  return held;
}

/** A countdown from a step ("20 minutes"): start, pause, reset; buzzes and toasts when done. */
function Timer({ timer }: { timer: StepTimer }) {
  const [left, setLeft] = useState(timer.seconds);
  const [running, setRunning] = useState(false);
  const endsAt = useRef<number | null>(null);

  useEffect(() => {
    if (!running) return;
    endsAt.current = Date.now() + left * 1000;
    const id = setInterval(() => {
      const rest = Math.max(0, Math.round(((endsAt.current ?? 0) - Date.now()) / 1000));
      setLeft(rest);
      if (rest === 0) {
        setRunning(false);
        navigator.vibrate?.([300, 150, 300]);
        toast.success(`Timer done: ${timer.label}`);
      }
    }, 250);
    return () => clearInterval(id);
    // `left` is read once when starting; the interval tracks the end time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, timer.label]);

  const done = left === 0;
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 rounded-full border py-0.5 pr-0.5 pl-2.5 text-sm tabular-nums",
        done && "border-emerald-500 text-emerald-700 dark:text-emerald-400",
      )}
    >
      <TimerIcon aria-hidden className="size-3.5" />
      <span aria-live={running ? "off" : "polite"} aria-label={`${timer.label} timer`}>
        {clock(left)}
      </span>
      {done ? null : (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={running ? `Pause ${timer.label}` : `Start ${timer.label}`}
          onClick={() => setRunning(!running)}
        >
          {running ? <PauseIcon /> : <PlayIcon />}
        </Button>
      )}
      {left !== timer.seconds ? (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Reset ${timer.label}`}
          onClick={() => {
            setRunning(false);
            setLeft(timer.seconds);
          }}
        >
          <RotateCcwIcon />
        </Button>
      ) : null}
    </div>
  );
}

function amount(ing: Recipe["ingredients"][number], factor: number): string {
  if (factor === 1 || ing.grams == null) return ing.measure || "";
  return formatGrams(ing.grams * factor);
}

function CookView({ recipe, initial }: { recipe: Recipe; initial: number }) {
  const [servings, setServings] = useState(initial);
  const [got, setGot] = useState<Set<number>>(new Set());
  const [done, setDone] = useState<Set<number>>(new Set());
  const awake = useWakeLock();
  const factor = scaleFactor(servings, recipe.servings);
  const method = steps(recipe.instructions);
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
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{recipe.name}</h1>
        {awake ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <SunIcon aria-hidden className="size-3.5" />
            Your screen stays on while you cook.
          </p>
        ) : null}
      </header>

      <section aria-labelledby="cook-ingredients" className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h2 id="cook-ingredients" className="text-base font-semibold">
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
        <ul className="flex flex-col divide-y rounded-lg border text-sm">
          {recipe.ingredients.map((ing, i) => (
            <li key={`${ing.name}-${i}`}>
              <label className="flex cursor-pointer items-center gap-3 px-3 py-2.5">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={got.has(i)}
                  onChange={() => setGot(toggle(got, i))}
                />
                <span className={cn("w-20 shrink-0 tabular-nums", got.has(i) && "opacity-50")}>
                  {amount(ing, factor)}
                </span>
                <span className={cn("min-w-0 flex-1", got.has(i) && "line-through opacity-50")}>
                  {ing.name}
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
        <h2 id="cook-method" className="text-base font-semibold">
          Method
        </h2>
        <ol className="flex flex-col gap-3">
          {method.map((step, i) => {
            const finished = done.has(i);
            return (
              <li key={i} className="flex gap-3">
                <button
                  type="button"
                  aria-pressed={finished}
                  aria-label={`Step ${i + 1} done`}
                  onClick={() => setDone(toggle(done, i))}
                  className={cn(
                    "grid size-8 shrink-0 place-items-center rounded-full border text-sm font-semibold tabular-nums",
                    finished && "border-primary bg-primary text-primary-foreground",
                  )}
                >
                  {finished ? <CheckIcon aria-hidden className="size-4" /> : i + 1}
                </button>
                <div className="flex min-w-0 flex-1 flex-col gap-2 pt-1">
                  <p
                    className={cn(
                      "text-base leading-relaxed",
                      finished && "text-muted-foreground line-through",
                    )}
                  >
                    {step}
                  </p>
                  {finished ? null : (
                    <div className="flex flex-wrap gap-2">
                      {stepTimers(step).map((t, j) => (
                        <Timer key={`${i}-${j}`} timer={t} />
                      ))}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        {method.length && done.size === method.length ? (
          <p className="rounded-lg bg-muted p-3 text-sm font-medium" role="status">
            All done. Enjoy!
          </p>
        ) : null}
      </section>
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
