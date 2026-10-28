import { cn } from "cn";

import type { Macros, Plan, ReferenceIntakes } from "@/lib/api/hooks";

export const MICROS = [
  { key: "iron_mg", label: "Iron", unit: "mg" },
  { key: "calcium_mg", label: "Calcium", unit: "mg" },
  { key: "potassium_mg", label: "Potassium", unit: "mg" },
  { key: "vitamin_c_mg", label: "Vitamin C", unit: "mg" },
  { key: "vitamin_d_ug", label: "Vitamin D", unit: "µg" },
  { key: "folate_ug", label: "Folate", unit: "µg" },
  { key: "vitamin_b12_ug", label: "Vitamin B12", unit: "µg" },
] as const;

type MicroKey = (typeof MICROS)[number]["key"];

/** The EU labelling reference intakes for adults (the API's ReferenceIntakes defaults). */
export const LABEL_RI: Record<MicroKey, number> = {
  iron_mg: 14,
  calcium_mg: 800,
  potassium_mg: 2000,
  vitamin_c_mg: 80,
  vitamin_d_ug: 5,
  folate_ug: 200,
  vitamin_b12_ug: 2.5,
};

// Below this share of the reference intake, a day's average is marked.
const LOW = 0.5;

function amount(value: number, unit: string): string {
  const shown = value >= 10 ? Math.round(value).toLocaleString() : value.toFixed(1);
  return `${shown} ${unit}`;
}

/** For a value added up from only some meals: how many had data. */
type Coverage = { known: number; total: number };

/**
 * Vitamins and minerals against the reference intakes printed on food labels: per serving of a
 * recipe, or a plan's average day (marked when under half). For context only: the planner
 * doesn't aim for them. Unknown values (a food without data) say so instead of showing 0; a
 * value from only some meals (`partial`) shows as "at least" and is never marked low.
 */
export function Micronutrients({
  values,
  reference,
  mode,
  partial = {},
}: {
  values: Partial<Pick<Macros, MicroKey>>;
  reference?: Partial<ReferenceIntakes>;
  mode: "serving" | "day";
  partial?: Partial<Record<MicroKey, Coverage>>;
}) {
  if (MICROS.every(({ key }) => values[key] === null || values[key] === undefined)) return null;
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-2" aria-label="Vitamins and minerals">
        {MICROS.map(({ key, label, unit }) => {
          const value = values[key];
          const ri = reference?.[key] ?? LABEL_RI[key];
          const known = value !== null && value !== undefined;
          const share = known ? value / ri : 0;
          const some = partial[key];
          const low = mode === "day" && known && !some && share < LOW;
          return (
            <li key={key} className="grid grid-cols-[6.5rem_1fr_auto] items-center gap-3 text-sm">
              <span>{label}</span>
              <span aria-hidden className="h-2 overflow-hidden rounded-full bg-muted">
                <span
                  className={cn("block h-full rounded-full", low ? "bg-amber-500" : "bg-primary")}
                  style={{ width: `${Math.min(100, share * 100)}%` }}
                />
              </span>
              <span
                className={cn(
                  "text-right text-xs tabular-nums",
                  low ? "text-warning" : "text-muted-foreground",
                )}
              >
                {known && some ? (
                  <>
                    at least {amount(value, unit)} · {Math.round(share * 100)}%
                    <span className="block">
                      data for {some.known} of {some.total} meals
                    </span>
                  </>
                ) : known ? (
                  <>
                    {amount(value, unit)} · {Math.round(share * 100)}%{low ? " (low)" : ""}
                  </>
                ) : (
                  "no data"
                )}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-muted-foreground">
        % of the reference intake on food labels (adults),{" "}
        {mode === "day" ? "a day" : "a day, per serving"}.
        {mode === "day" ? " Most vitamin D comes from sunlight, not food." : ""}
      </p>
    </div>
  );
}

/**
 * A plan's average day of vitamins and minerals, added up from its meals. Where only some
 * meals have data for one, it is the average of what is known: a lower bound, shown as such.
 */
export function WeekMicronutrients({ plan }: { plan: Plan }) {
  const days = plan.days.length || 1;
  const meals = plan.days.flatMap((d) => d.meals);
  const average: Partial<Pick<Macros, MicroKey>> = {};
  const partial: Partial<Record<MicroKey, Coverage>> = {};
  for (const { key } of MICROS) {
    const known = meals
      .map((m) => m.nutrition[key])
      .filter((v): v is number => v !== null && v !== undefined);
    average[key] = known.length ? known.reduce((a, b) => a + b, 0) / days : null;
    if (known.length && known.length < meals.length) {
      partial[key] = { known: known.length, total: meals.length };
    }
  }
  if (MICROS.every(({ key }) => average[key] === null)) return null;
  return (
    <section aria-labelledby="week-micros" className="flex flex-col gap-2">
      <h2 id="week-micros" className="text-lg font-semibold">
        Vitamins and minerals
      </h2>
      <p className="text-sm text-muted-foreground">An average day of this plan.</p>
      <Micronutrients
        values={average}
        reference={plan.targets.reference}
        mode="day"
        partial={partial}
      />
    </section>
  );
}
