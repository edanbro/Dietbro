import { cn } from "cn";
import { ArrowDownIcon, ArrowUpIcon, CheckIcon } from "lucide-react";

import type { Macros, NutrientBands, ReferenceIntakes } from "@/lib/api/hooks";
import { type Band, bandStatus, formatBand, formatNumber } from "@/lib/format";

type Props = {
  label: string;
  value: number;
  unit: string;
  band: Band | null | undefined;
  /** Hard limits (kcal) must be met; soft ones (macros) are aimed for. */
  hard?: boolean;
};

/**
 * A bullet-style meter: the shaded range is the target band, the thin bar the planned amount.
 * Off-target states always carry an icon and words, never colour alone.
 */
export function MacroBar({ label, value, unit, band, hard = false }: Props) {
  const status = bandStatus(value, band);
  const target = formatBand(band, unit);
  const min = band?.min ?? null;
  const max = band?.max ?? null;
  const off = status === "below" || status === "above";
  const gap = status === "below" ? (min ?? 0) - value : status === "above" ? value - (max ?? 0) : 0;
  const verdict = off
    ? `${formatNumber(gap)} ${unit} ${status === "below" ? "under" : "over"}`
    : status === "within"
      ? "On target"
      : null;

  const scale = Math.max(value, max ?? min ?? 0) * 1.15 || 1;
  const pct = (x: number) => `${Math.min(100, Math.max(0, (x / scale) * 100))}%`;
  const VerdictIcon =
    status === "below" ? ArrowDownIcon : status === "above" ? ArrowUpIcon : CheckIcon;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums">
          {formatNumber(value)} {unit}
        </span>
      </div>
      {status === "none" ? (
        <p className="text-xs text-muted-foreground">No target set</p>
      ) : (
        <>
          <div
            role="meter"
            aria-label={label}
            aria-valuenow={value}
            aria-valuemin={0}
            aria-valuemax={Math.round(scale)}
            aria-valuetext={`${formatNumber(value)} ${unit}, target ${target}${off ? `, ${verdict}` : ""}`}
            data-status={status}
            className="relative h-3 rounded-full bg-muted"
          >
            <div
              aria-hidden
              className="absolute inset-y-0 rounded-full bg-foreground/15"
              style={{
                left: pct(min ?? 0),
                right: max === null ? 0 : `calc(100% - ${pct(max)})`,
              }}
            />
            <div
              aria-hidden
              className={cn(
                "absolute top-1/2 left-0 h-1.5 -translate-y-1/2 rounded-full",
                !off && "bg-foreground",
                off && hard && "bg-destructive",
                off && !hard && "bg-amber-500",
              )}
              style={{ width: pct(value) }}
            />
          </div>
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>Target {target}</span>
            <span
              className={cn(
                "flex items-center gap-1",
                off && hard && "text-destructive",
                off && !hard && "text-amber-700 dark:text-amber-400",
              )}
            >
              <VerdictIcon aria-hidden className="size-3" />
              {verdict}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

/** One day's totals against the daily bands: calories are hard, macros soft. */
export function DayMacros({
  totals,
  bands,
  reference,
}: {
  totals: Macros;
  bands: NutrientBands;
  reference?: ReferenceIntakes;
}) {
  return (
    <section aria-label="Day totals" className="flex flex-col gap-3">
      <MacroBar label="Calories" unit="kcal" value={totals.kcal} band={bands.kcal} hard />
      <MacroBar label="Protein" unit="g" value={totals.protein_g} band={bands.protein_g} />
      <MacroBar label="Carbs" unit="g" value={totals.carbs_g} band={bands.carbs_g} />
      <MacroBar label="Fat" unit="g" value={totals.fat_g} band={bands.fat_g} />
      <MoreNutrients values={totals} reference={reference} />
      <p className="text-xs text-muted-foreground">
        Calories are a firm range. Protein, carbs and fat are aimed for, so a day can be a little
        off while the week balances out.
      </p>
    </section>
  );
}

const MORE = [
  { key: "fiber_g", label: "Fibre", atLeast: true },
  { key: "sugars_g", label: "Sugars", atLeast: false },
  { key: "sat_fat_g", label: "Sat fat", atLeast: false },
  { key: "salt_g", label: "Salt", atLeast: false },
] as const;

/**
 * Fibre, sugars, saturated fat and salt. With `reference` (daily guides), each shows the guide
 * and is marked when it misses it: fibre below, the others above. Hidden when nothing is known.
 */
export function MoreNutrients({
  values,
  reference,
}: {
  values: Pick<Macros, "fiber_g" | "sugars_g" | "sat_fat_g" | "salt_g">;
  reference?: ReferenceIntakes;
}) {
  if (MORE.every((m) => values[m.key] === null || values[m.key] === undefined)) return null;
  return (
    <dl className="grid grid-cols-4 gap-2" aria-label="More nutrients">
      {MORE.map(({ key, label, atLeast }) => {
        const value = values[key];
        const guide = reference?.[key];
        const off =
          value !== null && value !== undefined && guide !== undefined
            ? atLeast
              ? value < guide
              : value > guide
            : false;
        return (
          <div key={key} className="flex flex-col items-center rounded-lg bg-muted/60 px-1 py-2">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd
              className={`text-sm font-semibold tabular-nums ${off ? "text-amber-600 dark:text-amber-400" : ""}`}
            >
              {value === null || value === undefined ? "–" : `${value.toFixed(1)} g`}
            </dd>
            {guide !== undefined ? (
              <dd className="text-[0.7rem] text-muted-foreground">
                {atLeast ? "aim ≥" : "max"} {guide} g
              </dd>
            ) : null}
          </div>
        );
      })}
    </dl>
  );
}
