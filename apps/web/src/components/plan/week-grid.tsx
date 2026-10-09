import Link from "next/link";

import type { PlanDay, Slot } from "@/lib/api/hooks";
import { dayOfMonth, weekday } from "@/lib/dates";
import { formatNumber, servingsLabel } from "@/lib/format";

import { REQUIRED_SLOTS, SLOT_LABEL, SLOT_ORDER } from "./slots";

/** Compact week at a glance: one row per day, one column per meal of the day. */
export function WeekGrid({
  days,
  today,
  onPickDay,
}: {
  days: PlanDay[];
  today: string;
  onPickDay: (date: string) => void;
}) {
  const used = new Set(days.flatMap((d) => d.meals.map((m) => m.slot)));
  const slots: Slot[] = SLOT_ORDER.filter((s) => REQUIRED_SLOTS.includes(s) || used.has(s));

  return (
    <table className="w-full table-fixed border-separate border-spacing-0 text-xs">
      <caption className="sr-only">Meals this week</caption>
      <thead>
        <tr>
          <th scope="col" className="w-14 pb-1.5 text-left font-medium text-muted-foreground">
            <span className="sr-only">Day</span>
          </th>
          {slots.map((s) => (
            <th
              key={s}
              scope="col"
              className="px-1 pb-1.5 text-left font-medium text-muted-foreground"
            >
              {SLOT_LABEL[s]}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {days.map((day) => (
          <tr key={day.date} aria-current={day.date === today ? "date" : undefined}>
            <th scope="row" className="border-t py-1.5 pr-1 text-left align-top font-normal">
              <button
                type="button"
                onClick={() => onPickDay(day.date)}
                className="flex flex-col items-start rounded-md text-left focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                aria-label={`Open ${weekday(day.date)} ${dayOfMonth(day.date)}`}
              >
                <span className={day.date === today ? "font-semibold" : "font-medium"}>
                  {weekday(day.date)} {dayOfMonth(day.date)}
                </span>
                <span className="text-muted-foreground tabular-nums">
                  {formatNumber(day.totals.kcal)} kcal
                </span>
              </button>
            </th>
            {slots.map((s) => {
              const meal = day.meals.find((m) => m.slot === s);
              return (
                <td key={s} className="border-t px-1 py-1.5 align-top">
                  {meal ? (
                    <Link
                      href={`/recipes/${meal.recipe.id}`}
                      className="line-clamp-3 leading-snug hover:underline"
                      title={`${meal.recipe.name}, ${servingsLabel(meal.portions)}`}
                    >
                      {meal.recipe.name}
                    </Link>
                  ) : (
                    <span className="text-muted-foreground">
                      <span aria-hidden>—</span>
                      <span className="sr-only">No {SLOT_LABEL[s].toLowerCase()}</span>
                    </span>
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
