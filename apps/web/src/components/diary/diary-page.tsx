"use client";

import { cn } from "cn";
import { Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, LabeledInput } from "@/components/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type DiaryDay, useDiary, useWeight, useWeights } from "@/lib/api/hooks";
import { localISODate, shortDate } from "@/lib/dates";
import { formatNumber, humanize } from "@/lib/format";

import { QuickAdd } from "./quick-add";
import { PriceWatch } from "./price-watch";
import { SpendingSection } from "./spending";
import { WeightChart } from "./weight-chart";

const STATUS: Record<NonNullable<DiaryDay["status"]>, { label: string; className: string }> = {
  under: { label: "Under", className: "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100" },
  on: {
    label: "On target",
    className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
  },
  over: {
    label: "Over",
    className: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100",
  },
};

/** "Eaten 1,450 of 1,800–2,200 kcal" */
export function eatenText(kcal: number, min?: number | null, max?: number | null): string {
  const band =
    min && max
      ? `${formatNumber(min)}–${formatNumber(max)}`
      : min
        ? `at least ${formatNumber(min)}`
        : max
          ? `up to ${formatNumber(max)}`
          : null;
  return band ? `Eaten ${formatNumber(kcal)} of ${band} kcal` : `Eaten ${formatNumber(kcal)} kcal`;
}

function DayRow({ day, today }: { day: DiaryDay; today: string }) {
  const [open, setOpen] = useState(false);
  const status = day.status ? STATUS[day.status] : null;
  const isToday = day.date === today;
  return (
    <li className="flex flex-col">
      <button
        type="button"
        className="flex items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50 disabled:hover:bg-transparent"
        aria-expanded={day.logged.length ? open : undefined}
        disabled={!day.logged.length}
        onClick={() => setOpen(!open)}
      >
        <span className="w-24 shrink-0 text-sm font-medium">
          {isToday ? "Today" : shortDate(day.date)}
        </span>
        <span className="min-w-0 flex-1 text-sm tabular-nums">
          {day.logged.length ? (
            `${formatNumber(day.eaten.kcal)} kcal`
          ) : (
            <span className="text-muted-foreground">Nothing logged</span>
          )}
          {day.planned_kcal ? (
            <span className="text-xs text-muted-foreground">
              {" "}
              · planned {formatNumber(day.planned_kcal)}
            </span>
          ) : null}
        </span>
        {status && !isToday ? (
          <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", status.className)}>
            {status.label}
          </span>
        ) : null}
      </button>
      {open ? (
        <ul className="flex flex-col gap-1 px-3 pb-2.5 text-xs text-muted-foreground">
          {day.logged.map((l, i) => (
            <li key={`${l.description}-${i}`} className="flex justify-between gap-2">
              <span className="min-w-0 truncate">
                {l.slot ? `${humanize(l.slot)}: ` : ""}
                {l.kind === "skipped" ? "Skipped " : ""}
                {l.description}
              </span>
              <span className="shrink-0 tabular-nums">
                {formatNumber(l.kcal)} kcal{l.estimated ? " (est.)" : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function Weights() {
  const weights = useWeights();
  const save = useWeight();
  const [kg, setKg] = useState("");
  const today = localISODate();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const value = Number(kg.replace(",", "."));
    if (!Number.isFinite(value) || value <= 20) return;
    save.mutate(
      { kind: "save", measured_on: today, weight_kg: value },
      {
        onSuccess: () => {
          setKg("");
          toast.success("Weight saved");
        },
      },
    );
  };

  return (
    <section aria-labelledby="weight" className="flex flex-col gap-3">
      <h2 id="weight" className="text-base font-semibold">
        Weight
      </h2>
      <form onSubmit={submit} className="flex items-end gap-2" aria-label="Add today's weight">
        <div className="flex-1">
          <LabeledInput
            id="weight-kg"
            label="Today (kg)"
            inputMode="decimal"
            value={kg}
            onChange={(e) => setKg(e.target.value)}
            placeholder="e.g. 72.4"
          />
        </div>
        <Button type="submit" disabled={!kg || save.isPending}>
          Save
        </Button>
      </form>
      <ErrorAlert error={save.error} />
      {weights.isPending ? (
        <Skeleton className="h-36" />
      ) : weights.error ? (
        <ErrorAlert error={weights.error} onRetry={() => void weights.refetch()} />
      ) : (
        <>
          <WeightChart weights={weights.data} />
          {weights.data.length ? (
            <ul className="flex flex-col divide-y rounded-lg border text-sm">
              {weights.data
                .slice(-5)
                .reverse()
                .map((w) => (
                  <li key={w.measured_on} className="flex items-center gap-3 px-3 py-1">
                    <span className="flex-1">{shortDate(w.measured_on)}</span>
                    <span className="tabular-nums">{w.weight_kg} kg</span>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete the weigh-in of ${shortDate(w.measured_on)}`}
                      onClick={() => save.mutate({ kind: "delete", measured_on: w.measured_on })}
                    >
                      <Trash2Icon />
                    </Button>
                  </li>
                ))}
            </ul>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Your newest weigh-in also updates your profile, so calorie suggestions follow it.
          </p>
        </>
      )}
    </section>
  );
}

/** The last two weeks of what was eaten against the goals, and weigh-ins with their trend. */
export function DiaryPage() {
  const diary = useDiary(14);
  const [allDays, setAllDays] = useState(false);

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Diary</h1>
      {diary.isPending ? (
        <div className="flex flex-col gap-2" aria-busy>
          <Skeleton className="h-16" />
          <Skeleton className="h-64" />
        </div>
      ) : diary.error ? (
        <ErrorAlert error={diary.error} onRetry={() => void diary.refetch()} />
      ) : (
        <>
          <section aria-labelledby="diary-summary" className="flex flex-col gap-1">
            <h2 id="diary-summary" className="sr-only">
              Summary
            </h2>
            <p className="text-lg font-semibold">
              {eatenText(
                diary.data.days.at(-1)?.eaten.kcal ?? 0,
                diary.data.kcal_min,
                diary.data.kcal_max,
              )}{" "}
              today
            </p>
            <p className="text-sm text-muted-foreground">
              {diary.data.logged_days ? (
                <>
                  On target{" "}
                  <Badge variant="secondary">
                    {diary.data.on_target_days} of {diary.data.logged_days}
                  </Badge>{" "}
                  logged days in the last two weeks.
                </>
              ) : (
                "Mark meals eaten on your plan, or tell the chat what you had, and they show up here."
              )}
            </p>
          </section>
          <QuickAdd />
          <section aria-labelledby="diary-days" className="flex flex-col gap-2">
            <h2 id="diary-days" className="text-base font-semibold">
              Days
            </h2>
            <ul className="flex flex-col divide-y rounded-lg border">
              {[...diary.data.days]
                .reverse()
                .slice(0, allDays ? undefined : 7)
                .map((d) => (
                  <DayRow key={d.date} day={d} today={diary.data.today} />
                ))}
            </ul>
            {diary.data.days.length > 7 ? (
              <Button
                variant="ghost"
                size="sm"
                className="self-start"
                aria-expanded={allDays}
                onClick={() => setAllDays(!allDays)}
              >
                {allDays ? "Show the last week" : `Show all ${diary.data.days.length} days`}
              </Button>
            ) : null}
          </section>
        </>
      )}
      <Weights />
      <SpendingSection />
      <PriceWatch />
    </div>
  );
}
