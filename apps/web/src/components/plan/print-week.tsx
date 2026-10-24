"use client";

import type { Plan, Slot } from "@/lib/api/hooks";
import { dateRange, dayOfMonth, weekday } from "@/lib/dates";
import { formatNumber, formatServings } from "@/lib/format";
import { usePrinting } from "@/lib/use-printing";

import { loggedShort } from "./logged";
import { REQUIRED_SLOTS, SLOT_LABEL, SLOT_ORDER } from "./slots";

/**
 * The week on paper: a row per day, a column per meal with its servings and kcal. Only there
 * while printing (the plan page's own layout is for the screen); for the fridge door.
 */
export function PrintWeek({ plan }: { plan: Plan }) {
  const printing = usePrinting();
  if (!printing) return null;
  const used = new Set(
    plan.days.flatMap((d) => [...d.meals.map((m) => m.slot), ...d.logged.map((l) => l.slot)]),
  );
  const skipped = plan.skipped_meals ?? [];
  const own = (plan.own_meals ?? []).map((o) => o.slot);
  const slots: Slot[] = SLOT_ORDER.filter(
    (s) => (REQUIRED_SLOTS.includes(s) && !skipped.includes(s)) || used.has(s),
  );
  const first = plan.days[0]?.date ?? plan.start;
  const last = plan.days.at(-1)?.date ?? plan.start;
  return (
    <section className="hidden flex-col gap-3 print:flex" data-testid="print-week">
      <div>
        <h1 className="text-2xl font-semibold">Meals for {dateRange(first, last)}</h1>
        {plan.household > 1 ? (
          <p className="text-sm text-muted-foreground">
            Servings are each person&apos;s; cook for {plan.household}.
          </p>
        ) : null}
      </div>
      <table className="w-full table-fixed border-collapse text-sm">
        <thead>
          <tr>
            <th scope="col" className="w-20 border-b py-1.5 text-left font-medium">
              Day
            </th>
            {slots.map((s) => (
              <th key={s} scope="col" className="border-b px-2 py-1.5 text-left font-medium">
                {SLOT_LABEL[s]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {plan.days.map((day) => (
            <tr key={day.date} className="break-inside-avoid">
              <th scope="row" className="border-b py-2 pr-2 text-left align-top font-medium">
                {weekday(day.date)} {dayOfMonth(day.date)}
                <span className="block text-xs font-normal text-muted-foreground">
                  {formatNumber(day.totals.kcal)} kcal
                </span>
              </th>
              {slots.map((s) => {
                const meal = day.meals.find((m) => m.slot === s);
                const logged = day.logged.find((l) => l.slot === s);
                return (
                  <td key={s} className="border-b px-2 py-2 align-top">
                    {meal ? (
                      <>
                        <span className="block leading-snug">{meal.recipe.name}</span>
                        <span className="text-xs text-muted-foreground">
                          {formatServings(meal.portions)} · {formatNumber(meal.nutrition.kcal)} kcal
                        </span>
                      </>
                    ) : logged ? (
                      <span className="text-muted-foreground">{loggedShort(logged)}</span>
                    ) : own.includes(s) ? (
                      <span className="text-muted-foreground italic">Your own</span>
                    ) : (
                      <span className="text-muted-foreground">–</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
