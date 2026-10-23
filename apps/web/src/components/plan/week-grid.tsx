import { cn } from "cn";
import { CircleCheckIcon } from "lucide-react";
import Link from "next/link";

import type { PlanDay, Slot } from "@/lib/api/hooks";
import { dayOfMonth, weekday } from "@/lib/dates";
import { formatNumber, servingsLabel } from "@/lib/format";

import { loggedShort } from "./logged";
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
    <>
      <WeekColumns days={days} today={today} slots={slots} onPickDay={onPickDay} />
      <WeekTable days={days} today={today} slots={slots} onPickDay={onPickDay} />
    </>
  );
}

type Props = {
  days: PlanDay[];
  today: string;
  slots: Slot[];
  onPickDay: (date: string) => void;
};

/** Wide screens: a column per day, meals as small cards, today highlighted. */
function WeekColumns({ days, today, slots, onPickDay }: Props) {
  return (
    <ol aria-label="Days this week" className="hidden grid-cols-7 gap-2 lg:grid">
      {days.map((day) => {
        const isToday = day.date === today;
        return (
          <li
            key={day.date}
            aria-current={isToday ? "date" : undefined}
            className={cn(
              "flex min-w-0 flex-col gap-1.5 rounded-xl border p-2",
              isToday ? "border-primary/60 bg-accent/40" : "bg-card",
            )}
          >
            <button
              type="button"
              onClick={() => onPickDay(day.date)}
              className="flex flex-col items-start rounded-md text-left focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
              aria-label={`Open ${weekday(day.date)} ${dayOfMonth(day.date)}`}
            >
              <span className={cn("text-sm", isToday ? "font-semibold text-primary" : "font-medium")}>
                {weekday(day.date)} {dayOfMonth(day.date)}
              </span>
              <span className="text-xs text-muted-foreground tabular-nums">
                {formatNumber(day.totals.kcal)} kcal
              </span>
            </button>
            {slots.map((s) => {
              const meal = day.meals.find((m) => m.slot === s);
              const logged = day.logged.find((l) => l.slot === s);
              return (
                <div key={s} className="rounded-lg bg-muted/50 p-1.5 text-xs">
                  <span className="block text-[0.7rem] text-muted-foreground">{SLOT_LABEL[s]}</span>
                  {meal ? (
                    <Link
                      href={`/recipes/${meal.recipe.id}?servings=${meal.servings}`}
                      className="line-clamp-3 leading-snug font-medium hover:underline"
                      title={`${meal.recipe.name}, ${servingsLabel(meal.portions)}`}
                    >
                      {meal.status === "eaten" ? (
                        <CircleCheckIcon
                          aria-hidden
                          className="mr-0.5 inline size-3 align-[-0.1em] text-emerald-700 dark:text-emerald-400"
                        />
                      ) : null}
                      {meal.recipe.name}
                      {meal.status === "eaten" ? <span className="sr-only"> (eaten)</span> : null}
                    </Link>
                  ) : logged ? (
                    <span className="line-clamp-3 leading-snug text-muted-foreground italic">
                      {loggedShort(logged)}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">
                      <span aria-hidden>—</span>
                      <span className="sr-only">No {SLOT_LABEL[s].toLowerCase()}</span>
                    </span>
                  )}
                </div>
              );
            })}
          </li>
        );
      })}
    </ol>
  );
}

/** Phones: one row per day, one column per meal of the day. */
function WeekTable({ days, today, slots, onPickDay }: Props) {
  return (
    <table className="w-full table-fixed border-separate border-spacing-0 text-xs lg:hidden">
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
              const logged = day.logged.find((l) => l.slot === s);
              return (
                <td key={s} className="border-t px-1 py-1.5 align-top">
                  {meal ? (
                    <Link
                      href={`/recipes/${meal.recipe.id}`}
                      className="line-clamp-3 leading-snug hover:underline"
                      title={`${meal.recipe.name}, ${servingsLabel(meal.portions)}`}
                    >
                      {meal.status === "eaten" ? (
                        <CircleCheckIcon
                          aria-hidden
                          className="mr-0.5 inline size-3 align-[-0.1em] text-emerald-700 dark:text-emerald-400"
                        />
                      ) : null}
                      {meal.recipe.name}
                      {meal.status === "eaten" ? (
                        <>
                          {" "}
                          <span className="sr-only">(eaten)</span>
                        </>
                      ) : null}
                    </Link>
                  ) : logged ? (
                    <span className="line-clamp-3 leading-snug text-muted-foreground italic">
                      {loggedShort(logged)}
                    </span>
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
