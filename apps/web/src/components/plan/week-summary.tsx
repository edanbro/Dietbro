import { cn } from "cn";
import { TriangleAlertIcon } from "lucide-react";

import type { Plan } from "@/lib/api/hooks";
import { formatBand, formatGrams, formatMoney, formatNumber } from "@/lib/format";

import { MacroBar } from "./macro-bars";

function Stat({
  label,
  value,
  note,
  warn = false,
}: {
  label: string;
  value: string;
  note: React.ReactNode;
  warn?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg bg-muted/60 p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
      <dd
        className={cn(
          "flex items-center gap-1 text-xs",
          warn ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {warn ? <TriangleAlertIcon aria-hidden className="size-3" /> : null}
        {note}
      </dd>
    </div>
  );
}

/** Whole-plan numbers: energy, protein against the weekly band, cost, pantry use and waste. */
export function WeekSummary({ plan }: { plan: Plan }) {
  const days = plan.days.length || 1;
  const avgKcal = Math.round(plan.week_totals.kcal / days);
  const dailyKcal = formatBand(plan.targets.daily.kcal, "kcal");
  const cost = `≈ ${formatMoney(plan.cost_minor, plan.currency)}`;
  const budget = plan.budget_minor;
  const over = budget !== null && plan.cost_minor > budget;

  return (
    <section aria-labelledby="week-summary" className="flex flex-col gap-3">
      <h2 id="week-summary" className="text-base font-semibold">
        This plan
      </h2>
      <dl className="grid grid-cols-2 gap-2">
        <Stat
          label="Average per day"
          value={`${formatNumber(avgKcal)} kcal`}
          note={dailyKcal ? `target ${dailyKcal}` : "no daily target"}
        />
        <Stat
          label="Estimated cost"
          value={cost}
          warn={over}
          note={
            budget === null
              ? "no budget set"
              : over
                ? `${formatMoney(plan.cost_minor - budget, plan.currency)} over your ${formatMoney(budget, plan.currency)} budget`
                : `budget ${formatMoney(budget, plan.currency)}`
          }
        />
        <Stat
          label="From your pantry"
          value={formatGrams(plan.pantry_used_g)}
          note="of food you already have"
        />
        <Stat
          label="Waste"
          value={formatGrams(plan.waste_g)}
          note={plan.waste_g ? "pantry food expiring unused" : "nothing expires unused"}
        />
      </dl>
      <MacroBar
        label={`Protein over ${days} days`}
        unit="g"
        value={plan.week_totals.protein_g}
        band={plan.targets.weekly.protein_g}
      />
      <p className="text-xs text-muted-foreground">
        Costs are estimates from typical UK supermarket prices.
      </p>
    </section>
  );
}
