"use client";

import {
  ArrowLeftIcon,
  CircleCheckIcon,
  CircleSlashIcon,
  CookingPotIcon,
  NotebookPenIcon,
  RefreshCwIcon,
  Undo2Icon,
} from "lucide-react";
import { useId, useState } from "react";

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
  useAlternatives,
} from "@/lib/api/hooks";
import { formatGrams, formatNumber } from "@/lib/format";

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
};

type Mode = "menu" | "skip" | "other" | "swap";

/** "200 g chickpeas", "200 g chickpeas and 1 kg rice", "a, b and c". */
function foodList(items: PantryChange[]): string {
  const parts = items.map((i) => `${formatGrams(i.grams)} ${i.name.toLowerCase()}`);
  return parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}` : parts[0];
}

/** The toast after marking (or unmarking) a meal eaten: title and what the pantry did. */
export function eatenMessage(out: Eaten, undo: boolean): { title: string; description?: string } {
  const slot = SLOT_LABEL[out.slot];
  if (!out.changed) {
    return { title: undo ? `${slot} wasn't marked eaten` : `${slot} was already marked eaten` };
  }
  const lines: string[] = [];
  const moved = undo ? out.pantry.filter((p) => p.remaining_quantity !== null) : out.pantry;
  if (moved.length) {
    lines.push(
      undo
        ? `Put ${foodList(moved)} back in your pantry.`
        : `Took ${foodList(moved)} from your pantry.`,
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
  onDone,
}: MealActionsProps & { id: string; meal: Meal; onDone: () => void }) {
  const [mode, setMode] = useState<Mode>("menu");
  const [other, setOther] = useState("");
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
  const options = useAlternatives(planId, date, slot, mode === "swap");

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
                  {slot === "dinner" && cookExtraFor ? (
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() =>
                        replan({
                          intent: "swap",
                          when: { date: cookExtraFor, slot: "lunch" },
                          recipe_id: meal.recipe.id,
                        })
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
          {options.isPending ? (
            <>
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </>
          ) : (
            (options.data ?? []).map((o) => (
              <Button
                key={o.id}
                variant="outline"
                className="h-auto justify-between py-2 text-left"
                onClick={() => replan({ intent: "swap", when, recipe_id: o.id })}
              >
                <span className="min-w-0 truncate">{o.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {formatNumber(o.kcal_per_serving)} kcal
                </span>
              </Button>
            ))
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
