import { CircleCheckIcon, CircleSlashIcon, NotebookPenIcon } from "lucide-react";
import Link from "next/link";

import type { LoggedEntry, Meal, PlanDay } from "@/lib/api/hooks";
import { formatNumber } from "@/lib/format";

import { SLOT_ICON, SLOT_LABEL, SLOT_ORDER } from "./slots";

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/**
 * "Pizza (off-plan, ~850 kcal est.)", "Skipped – eating out (~650 kcal counted)", "Skipped",
 * "Lentil stew (eaten, 540 kcal)".
 */
export function loggedLabel(entry: LoggedEntry): string {
  const kcal = formatNumber(entry.kcal);
  if (entry.kind === "skipped") {
    return entry.kcal ? `Skipped – eating out (~${kcal} kcal counted)` : "Skipped";
  }
  if (entry.kind === "eaten") return `${capitalize(entry.description)} (eaten, ${kcal} kcal)`;
  const amount = entry.estimated ? `~${kcal} kcal est.` : `${kcal} kcal`;
  return `${capitalize(entry.description)} (off-plan, ${amount})`;
}

/** The week grid's short form: "Skipped", "Pizza (off-plan)", "Lentil stew (eaten)". */
export function loggedShort(entry: LoggedEntry): string {
  if (entry.kind === "skipped") return "Skipped";
  return `${capitalize(entry.description)} (${entry.kind === "eaten" ? "eaten" : "off-plan"})`;
}

export type DayRow =
  | { key: string; meal: Meal; entry?: undefined }
  | { key: string; entry: LoggedEntry; meal?: undefined };

/**
 * A day in eating order: each slot's meal, then what was logged for that slot (normally the
 * slot is empty then: a skip or an off-plan meal replaces it), then logs without a slot.
 */
export function dayRows(day: Pick<PlanDay, "meals" | "logged">): DayRow[] {
  const rows: DayRow[] = [];
  for (const slot of SLOT_ORDER) {
    for (const meal of day.meals.filter((m) => m.slot === slot)) rows.push({ key: slot, meal });
    day.logged.forEach((entry, i) => {
      if (entry.slot === slot) rows.push({ key: `log-${i}`, entry });
    });
  }
  day.logged.forEach((entry, i) => {
    if (entry.slot === null) rows.push({ key: `log-${i}`, entry });
  });
  return rows;
}

const KIND_ICON = { skipped: CircleSlashIcon, off_plan: NotebookPenIcon, eaten: CircleCheckIcon };

/**
 * Food the user logged: a skip or off-plan food (not a recipe, so not a link), or a planned meal
 * marked eaten that is no longer a row of the plan (it links to its recipe).
 */
export function LoggedCard({ entry }: { entry: LoggedEntry }) {
  const SlotIcon = entry.slot ? SLOT_ICON[entry.slot] : NotebookPenIcon;
  const KindIcon = KIND_ICON[entry.kind];
  const label = loggedLabel(entry);
  return (
    <div className="flex items-center gap-3 rounded-xl border border-dashed p-2.5">
      <div className="grid size-16 shrink-0 place-items-center rounded-lg bg-muted/50 text-muted-foreground">
        <KindIcon aria-hidden className="size-6" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <SlotIcon aria-hidden className="size-3.5" />
          {entry.slot ? SLOT_LABEL[entry.slot] : "Logged"}
        </span>
        {entry.kind === "eaten" && entry.recipe_id != null ? (
          <Link
            href={`/recipes/${entry.recipe_id}`}
            className="leading-snug font-medium underline-offset-4 hover:underline"
          >
            {label}
          </Link>
        ) : (
          <span className="leading-snug font-medium">{label}</span>
        )}
      </div>
    </div>
  );
}

/** Day totals count logged food too (`DayOut.totals` = meals + logged), so say so. */
export function LoggedNote({ logged }: { logged: LoggedEntry[] }) {
  const kcal = logged.reduce((sum, l) => sum + l.kcal, 0);
  if (!kcal) return null;
  const estimate = logged.some((l) => l.kcal && l.estimated);
  return (
    <p className="text-xs text-muted-foreground">
      Totals include {estimate ? "~" : ""}
      {formatNumber(kcal)} kcal of logged food{estimate ? " (estimated)" : ""}.
    </p>
  );
}
