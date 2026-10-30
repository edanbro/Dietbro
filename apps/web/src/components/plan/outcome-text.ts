import { CheckIcon, MinusIcon, XIcon } from "lucide-react";

import type { PlanOutcome, SlotChange } from "@/lib/api/hooks";
import { daysBetween, shortDate, weekday } from "@/lib/dates";
import { formatNumber, formatServings } from "@/lib/format";

type Logged = NonNullable<PlanOutcome["logged"]>[number];
type Result = NonNullable<PlanOutcome["results"]>[number];

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** "today", "Thu" (within a week), "Thu 22 Oct". */
export function dayName(date: string, today: string): string {
  if (date === today) return "today";
  return Math.abs(daysBetween(today, date)) <= 6 ? weekday(date) : shortDate(date);
}

/** "today's dinner", "Thu lunch", or just the day without a slot. */
export function mealName(date: string, slot: string | null | undefined, today: string): string {
  const day = dayName(date, today);
  if (!slot) return day;
  return date === today ? `today's ${slot}` : `${day} ${slot}`;
}

/** "Thu dinner: Lasagne → Chilli con carne", or a size change "Thu dinner: Lasagne (1 → 1½ servings)". */
export function changeText(c: SlotChange, today: string): string {
  const when = capitalize(mealName(c.date, c.slot, today));
  const before = c.before_portions;
  const after = c.after_portions;
  if (c.before === c.after && before != null && after != null && before !== after) {
    const size = (p: number) => formatServings(p).slice(1);
    return `${when}: ${c.after} (${size(before)} → ${size(after)} servings)`;
  }
  return `${when}: ${c.before ?? "no meal"} → ${c.after ?? "no meal"}`;
}

/** "Pizza – today's lunch, ~850 kcal (estimate)", "Skipped Thu dinner". */
export function loggedText(entry: Logged, today: string): string {
  const when = mealName(entry.date, entry.slot, today);
  const kcal = formatNumber(entry.kcal);
  if (entry.kind === "skipped") {
    return entry.kcal
      ? `Skipped ${when}, ~${kcal} kcal counted for eating out`
      : `Skipped ${when}`;
  }
  const amount = entry.estimated ? `~${kcal} kcal (estimate)` : `${kcal} kcal`;
  return `${capitalize(entry.description)} – ${when}, ${amount}`;
}

export const RESULT: Record<
  Result["status"],
  { label: string; icon: typeof CheckIcon; tone: string }
> = {
  applied: { label: "Done", icon: CheckIcon, tone: "text-foreground" },
  unchanged: { label: "Already done", icon: MinusIcon, tone: "text-muted-foreground" },
  failed: { label: "Not done", icon: XIcon, tone: "text-destructive" },
};
