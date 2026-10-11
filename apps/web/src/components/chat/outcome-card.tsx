import { cn } from "cn";
import {
  CalendarCheckIcon,
  CalendarIcon,
  CheckIcon,
  ChefHatIcon,
  ChevronRightIcon,
  MinusIcon,
  NotebookPenIcon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useId } from "react";

import type { ChatAttachment, ChatOutcome, SlotChange } from "@/lib/api/hooks";
import { daysBetween, shortDate, weekday } from "@/lib/dates";
import { formatBand, formatNumber, formatServings } from "@/lib/format";

type Logged = NonNullable<ChatOutcome["logged"]>[number];
type Result = NonNullable<ChatOutcome["results"]>[number];

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

function firstDate(outcome: ChatOutcome): string | null {
  const dates = [
    ...(outcome.changes ?? []).map((c) => c.date),
    ...(outcome.logged ?? []).map((l) => l.date),
    ...(outcome.results ?? []).map((r) => r.date),
  ].sort();
  return dates[0] ?? null;
}

/** What one plan change request did: per-request results, changed meals, logged food, days
 * now off target, warnings and notes, and a way to the plan. */
export function OutcomeCard({ outcome, today }: { outcome: ChatOutcome; today: string }) {
  const titleId = useId();
  const results = outcome.results ?? [];
  const changes = outcome.changes ?? [];
  const logged = outcome.logged ?? [];
  const offDays = (outcome.days ?? []).filter((d) => !d.within);
  const warnings = outcome.warnings ?? [];
  const notes = outcome.notes ?? [];
  const saved = outcome.plan_id != null;
  const title = saved ? "Plan updated" : logged.length ? "Logged" : "Plan unchanged";
  const Icon = saved ? CalendarCheckIcon : logged.length ? NotebookPenIcon : CalendarIcon;
  const day = firstDate(outcome);

  return (
    <article
      aria-labelledby={titleId}
      className="flex flex-col gap-2 rounded-xl border bg-card p-3 text-sm text-card-foreground"
    >
      <p id={titleId} className="flex items-center gap-1.5 font-medium">
        <Icon aria-hidden className="size-4" />
        {title}
      </p>
      {outcome.fresh ? (
        <p className="text-muted-foreground">I made a new plan for this week first.</p>
      ) : null}
      {results.length ? (
        <ul aria-label="Requests" className="flex flex-col gap-1">
          {results.map((r) => {
            const { label, icon: StatusIcon, tone } = RESULT[r.status];
            return (
              <li key={r.index} className={cn("flex gap-1.5", tone)}>
                <StatusIcon aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                <span>
                  <span className="sr-only">{label}: </span>
                  {r.message}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      {changes.length ? (
        <ul aria-label="Meal changes" className="flex flex-col gap-0.5">
          {changes.map((c) => (
            <li key={`${c.date}-${c.slot}`}>{changeText(c, today)}</li>
          ))}
        </ul>
      ) : null}
      {logged.length ? (
        <ul aria-label="Logged food" className="flex flex-col gap-0.5">
          {logged.map((l, i) => (
            <li key={`${l.date}-${l.slot}-${i}`}>{loggedText(l, today)}</li>
          ))}
        </ul>
      ) : null}
      {offDays.map((d) => (
        <p key={d.date} className="text-muted-foreground">
          {capitalize(dayName(d.date, today))} is now ~{formatNumber(d.kcal)} kcal,{" "}
          {d.kcal > d.max ? "above" : "below"} your {formatBand(d, "kcal")} range.
        </p>
      ))}
      {warnings.length ? (
        <ul
          aria-label="Warnings"
          className="flex flex-col gap-1 text-amber-800 dark:text-amber-200"
        >
          {warnings.map((w, i) => (
            <li key={`${i}-${w}`} className="flex gap-1.5">
              <TriangleAlertIcon aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {w}
            </li>
          ))}
        </ul>
      ) : null}
      {notes.map((n, i) => (
        <p key={`${i}-${n}`} className="text-xs text-muted-foreground">
          {n}
        </p>
      ))}
      {saved || logged.length ? (
        <Link
          href={day ? `/plan?day=${day}` : "/plan"}
          className="flex items-center gap-1 self-start font-medium underline-offset-4 hover:underline"
        >
          See plan
          <ChevronRightIcon aria-hidden className="size-4" />
        </Link>
      ) : null}
    </article>
  );
}

/** A recipe the assistant drafted for this user (nutrition and allergens computed by us). */
export function RecipeAttachment({ recipeId, name }: { recipeId: number; name: string }) {
  return (
    <Link
      href={`/recipes/${recipeId}`}
      className="flex items-center gap-3 rounded-xl border bg-card p-2.5 text-sm transition-colors hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
        <ChefHatIcon aria-hidden className="size-5" />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-xs text-muted-foreground">New recipe</span>
        <span className="line-clamp-2 font-medium">{name}</span>
      </span>
      <ChevronRightIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}

export function Attachment({ attachment, today }: { attachment: ChatAttachment; today: string }) {
  return attachment.type === "recipe" ? (
    <RecipeAttachment recipeId={attachment.recipe_id} name={attachment.name} />
  ) : (
    <OutcomeCard outcome={attachment} today={today} />
  );
}
