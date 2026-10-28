"use client";

import { cn } from "cn";
import {
  ArrowLeftIcon,
  ArrowLeftRightIcon,
  CircleCheckIcon,
  CircleSlashIcon,
  CookingPotIcon,
  NotebookPenIcon,
  RefreshCwIcon,
  Undo2Icon,
} from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type Eaten,
  type MealCell,
  type Meal,
  type PantryChange,
  type PlanChange,
  type PlanDay,
  type SwapFilters,
  useAlternatives,
} from "@/lib/api/hooks";
import { dayOfMonth, weekday } from "@/lib/dates";
import { foodName } from "@/lib/food-name";
import { formatMinutes, formatNumber } from "@/lib/format";
import { formatWeight, type Units } from "@/lib/units";

import { SLOT_LABEL } from "./slots";

/** What a meal card's options need from the page. */
export type MealActionsProps = {
  planId: number;
  date: string;
  today: string;
  /** A plan change is running (any meal): every action waits. */
  busy: boolean;
  /** Resolve when done; rejections are reported by the caller (toasts), not here. */
  onEaten: (cell: MealCell, undo: boolean) => Promise<unknown>;
  onReplan: (changes: PlanChange[]) => Promise<unknown>;
  /** Tomorrow's date when this dinner can be cooked in double for tomorrow's lunch. */
  cookExtraFor?: string | null;
  /** The plan's days: a meal in the same slot on another day can trade places with this one. */
  week?: PlanDay[];
};

type Mode = "menu" | "skip" | "other" | "swap" | "trade";

export type Trade = { date: string; meal: Meal };

/** The meals `meal` (on `date`) can trade places with: the same slot on the plan's other days
 * from `today` on, not eaten, and another recipe. */
export function tradesFor(week: PlanDay[], date: string, meal: Meal, today: string): Trade[] {
  return week.flatMap((day) =>
    day.date < today || day.date === date
      ? []
      : day.meals
          .filter(
            (m) => m.slot === meal.slot && m.status !== "eaten" && m.recipe.id !== meal.recipe.id,
          )
          .map((m) => ({ date: day.date, meal: m })),
  );
}

/** "200 g chickpeas", "200 g chickpeas and 1 kg rice", "a, b and c". */
function foodList(items: PantryChange[], units: Units): string {
  const parts = items.map(
    (i) => `${formatWeight(i.grams, units)} ${foodName(i.name).name.toLowerCase()}`,
  );
  return parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}` : parts[0];
}

/** The toast after marking (or unmarking) a meal eaten: title and what the pantry did. */
export function eatenMessage(
  out: Eaten,
  undo: boolean,
  units: Units = "metric",
): { title: string; description?: string } {
  const slot = SLOT_LABEL[out.slot];
  if (!out.changed) {
    return { title: undo ? `${slot} wasn't marked eaten` : `${slot} was already marked eaten` };
  }
  const lines: string[] = [];
  const moved = undo ? out.pantry.filter((p) => p.remaining_quantity !== null) : out.pantry;
  if (moved.length) {
    lines.push(
      undo
        ? `Put ${foodList(moved, units)} back in your pantry.`
        : `Took ${foodList(moved, units)} from your pantry.`,
    );
  }
  lines.push(...out.notes);
  return {
    title: undo ? `${slot} no longer marked eaten` : `${slot} marked eaten`,
    description: lines.length ? lines.join(" ") : undefined,
  };
}

/**
 * A meal's options, shown under its card. Today and earlier: mark eaten. Today and later: skip
 * (eating elsewhere or not), swap, and (today) log something else instead. An eaten meal can
 * only be unmarked.
 */
export function MealActions({
  id,
  meal,
  planId,
  date,
  today,
  busy,
  onEaten,
  onReplan,
  cookExtraFor = null,
  week = [],
  onDone,
}: MealActionsProps & { id: string; meal: Meal; onDone: () => void }) {
  const [mode, setMode] = useState<Mode>("menu");
  const [other, setOther] = useState("");
  // The swap picker's search (sent once typing pauses) and filters.
  const [typed, setTyped] = useState("");
  const [filters, setFilters] = useState<SwapFilters>({
    q: "",
    quick: false,
    pantry: false,
    favourites: false,
    cheaper: false,
  });
  useEffect(() => {
    const wait = setTimeout(() => setFilters((f) => ({ ...f, q: typed.trim() })), 300);
    return () => clearTimeout(wait);
  }, [typed]);
  const inputId = useId();
  const slot = meal.slot;
  const name = SLOT_LABEL[slot];
  const when = { date, slot };
  const eaten = meal.status === "eaten";
  const past = date < today;
  const future = date > today;

  const run = (action: Promise<unknown>) => {
    action.then(onDone, () => undefined);
  };
  const replan = (change: PlanChange) => run(onReplan([change]));
  const options = useAlternatives(planId, date, slot, mode === "swap", filters);
  const searching = Boolean(
    filters.q || filters.quick || filters.pantry || filters.favourites || filters.cheaper,
  );
  const trades = past ? [] : tradesFor(week, date, meal, today);
  // Each meal goes to the other's day: two swaps, made (and checked) as one change.
  const trade = (t: Trade) =>
    run(
      onReplan([
        { intent: "swap", when, recipe_id: t.meal.recipe.id },
        { intent: "swap", when: { date: t.date, slot }, recipe_id: meal.recipe.id },
      ]),
    );

  return (
    <div
      id={id}
      role="group"
      aria-label={`${name} options`}
      aria-busy={busy || undefined}
      className="flex flex-col gap-2 border-t p-2.5"
    >
      {mode === "menu" ? (
        <div className="flex flex-col gap-2">
          {eaten ? (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => run(onEaten(when, true))}
            >
              <Undo2Icon aria-hidden />
              Undo eaten
            </Button>
          ) : (
            <>
              {future ? null : (
                <Button
                      disabled={busy}
                  onClick={() => run(onEaten(when, false))}
                >
                  <CircleCheckIcon aria-hidden />
                  Mark eaten
                </Button>
              )}
              {past ? null : (
                <>
                  <Button variant="outline" disabled={busy} onClick={() => setMode("skip")}>
                    <CircleSlashIcon aria-hidden />
                    Skip
                  </Button>
                  <Button variant="outline" disabled={busy} onClick={() => setMode("swap")}>
                    <RefreshCwIcon aria-hidden />
                    Swap for something else
                  </Button>
                  {trades.length ? (
                    <Button variant="outline" disabled={busy} onClick={() => setMode("trade")}>
                      <ArrowLeftRightIcon aria-hidden />
                      Swap with another day
                    </Button>
                  ) : null}
                  {slot === "dinner" && cookExtraFor ? (
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() =>
                        // Tonight's dinner is pinned too, so the planner can't move it to make
                        // room for the lunch.
                        run(
                          onReplan([
                            { intent: "swap", when, recipe_id: meal.recipe.id },
                            {
                              intent: "swap",
                              when: { date: cookExtraFor, slot: "lunch" },
                              recipe_id: meal.recipe.id,
                            },
                          ]),
                        )
                      }
                    >
                      <CookingPotIcon aria-hidden />
                      Cook extra for tomorrow&apos;s lunch
                    </Button>
                  ) : null}
                </>
              )}
              {date === today ? (
                <Button
                  variant="outline"
                      disabled={busy}
                  onClick={() => setMode("other")}
                >
                  <NotebookPenIcon aria-hidden />
                  Had something else
                </Button>
              ) : null}
            </>
          )}
        </div>
      ) : null}

      {mode === "skip" ? (
        <fieldset className="flex flex-col gap-2" disabled={busy}>
          <legend className="mb-2 text-sm font-medium">Eating somewhere else instead?</legend>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => replan({ intent: "skip", when, eating_elsewhere: true })}
          >
            Yes, I&apos;ll eat elsewhere
          </Button>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => replan({ intent: "skip", when, eating_elsewhere: false })}
          >
            No, I&apos;m not eating
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => setMode("menu")}>
            <ArrowLeftIcon aria-hidden />
            Back
          </Button>
        </fieldset>
      ) : null}

      {mode === "swap" ? (
        <fieldset className="flex flex-col gap-2" disabled={busy}>
          <legend className="mb-2 text-sm font-medium">Swap {name.toLowerCase()} for:</legend>
          <Input
            type="search"
            aria-label="Search recipes"
            placeholder="Search, e.g. curry"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          <div className="flex flex-wrap gap-1.5">
            {(
              [
                ["quick", "Quick"],
                ["pantry", "Uses my pantry"],
                ["favourites", "Favourites"],
                ["cheaper", "Cheaper"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={filters[key]}
                onClick={() => setFilters((f) => ({ ...f, [key]: !f[key] }))}
                className={cn(
                  "inline-flex h-8 items-center rounded-full border px-3 text-xs transition-colors",
                  filters[key]
                    ? "border-primary bg-primary text-primary-foreground"
                    : "hover:bg-muted",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          {options.isPending ? (
            <>
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </>
          ) : options.data?.length ? (
            options.data.map((o) => (
              <Button
                key={o.id}
                variant="outline"
                className="h-auto justify-between py-2 text-left"
                onClick={() => replan({ intent: "swap", when, recipe_id: o.id })}
              >
                <span className="min-w-0 truncate">{o.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {o.minutes ? `${formatMinutes(o.minutes)} · ` : ""}
                  {formatNumber(o.kcal_per_serving)} kcal
                </span>
              </Button>
            ))
          ) : (
            <p className="text-sm text-muted-foreground" role="status">
              {searching ? "Nothing safe for you matches. Try other words." : "No close matches. Search above, or let the planner pick."}
            </p>
          )}
          <Button variant="outline" onClick={() => replan({ intent: "swap", when })}>
            Anything else - you pick
          </Button>
          <Button variant="ghost" onClick={() => setMode("menu")}>
            <ArrowLeftIcon aria-hidden />
            Back
          </Button>
        </fieldset>
      ) : null}

      {mode === "trade" ? (
        <fieldset className="flex flex-col gap-2" disabled={busy}>
          <legend className="mb-2 text-sm font-medium">
            Swap {name.toLowerCase()} with the one on:
          </legend>
          {trades.map((t) => (
            <Button
              key={t.date}
              variant="outline"
              className="h-auto justify-start gap-2 py-2 text-left"
              onClick={() => trade(t)}
            >
              <span className="w-14 shrink-0 font-medium">
                {weekday(t.date)} {dayOfMonth(t.date)}
              </span>{" "}
              <span className="min-w-0 truncate font-normal">{t.meal.recipe.name}</span>
            </Button>
          ))}
          <Button variant="ghost" onClick={() => setMode("menu")}>
            <ArrowLeftIcon aria-hidden />
            Back
          </Button>
        </fieldset>
      ) : null}

      {mode === "other" ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const description = other.trim();
            if (description) replan({ intent: "ate_off_plan", when, description });
          }}
        >
          <Label htmlFor={inputId}>What did you have?</Label>
          <Input
            id={inputId}
            value={other}
            maxLength={200}
            placeholder="e.g. 2 slices of pizza"
            autoComplete="off"
            onChange={(e) => setOther(e.target.value)}
          />
          <div className="flex gap-2">
            <Button type="submit" className="flex-1" disabled={busy || !other.trim()}>
              Log it
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => setMode("menu")}
            >
              <ArrowLeftIcon aria-hidden />
              Back
            </Button>
          </div>
        </form>
      ) : null}

      <p role="status" className={busy ? "text-xs text-muted-foreground" : "sr-only"}>
        {busy ? "Updating your plan…" : ""}
      </p>
    </div>
  );
}
