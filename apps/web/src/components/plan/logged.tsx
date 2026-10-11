import { CircleSlashIcon, NotebookPenIcon } from "lucide-react";

import type { LoggedEntry, Meal, PlanDay } from "@/lib/api/hooks";
import { formatNumber } from "@/lib/format";

import { SLOT_ICON, SLOT_LABEL, SLOT_ORDER } from "./slots";

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** "Pizza (off-plan, ~850 kcal est.)", "Skipped – eating out (~650 kcal counted)", "Skipped". */
export function loggedLabel(entry: LoggedEntry): string {
  const kcal = formatNumber(entry.kcal);
  if (entry.kind === "skipped") {
    return entry.kcal ? `Skipped – eating out (~${kcal} kcal counted)` : "Skipped";
  }
  const amount = entry.estimated ? `~${kcal} kcal est.` : `${kcal} kcal`;
  return `${capitalize(entry.description)} (off-plan, ${amount})`;
}

/** The week grid's short form: "Skipped", "Pizza (off-plan)". */
export function loggedShort(entry: LoggedEntry): string {
  return entry.kind === "skipped" ? "Skipped" : `${capitalize(entry.description)} (off-plan)`;
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

/** Food the user told the chat about: not a recipe, so not a link. */
export function LoggedCard({ entry }: { entry: LoggedEntry }) {
  const SlotIcon = entry.slot ? SLOT_ICON[entry.slot] : NotebookPenIcon;
  const KindIcon = entry.kind === "skipped" ? CircleSlashIcon : NotebookPenIcon;
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
        <span className="leading-snug font-medium">{loggedLabel(entry)}</span>
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
