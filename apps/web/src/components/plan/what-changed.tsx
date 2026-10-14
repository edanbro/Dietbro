"use client";

import { cn } from "cn";
import { CalendarCheckIcon, TriangleAlertIcon, Undo2Icon, XIcon } from "lucide-react";
import { useEffect, useId, useRef } from "react";

import { changeText, dayName, loggedText, RESULT } from "@/components/chat/outcome-card";
import { Button } from "@/components/ui/button";
import type { ChatOutcome, SlotChange } from "@/lib/api/hooks";
import { formatBand, formatNumber } from "@/lib/format";

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Why a meal changed: "you're skipping it" in "Thu dinner: Lentil stew → no meal — …". */
export function reasonText(c: SlotChange, today: string): string {
  switch (c.reason) {
    case "skip":
      return "you're skipping it";
    case "ate_off_plan":
      return "you had something else";
    case "swap":
      return "swapped as you asked";
    case "craving":
      return "you asked for it";
    case "rebalance":
      return `rebalanced to keep ${dayName(c.date, today)} on target`;
    case "resize":
      return "portion resized to fit the day";
  }
}

/** One line per changed meal: what it was, what it is now, and why. */
export function changeLine(c: SlotChange, today: string): string {
  return `${changeText(c, today)} — ${reasonText(c, today)}`;
}

/**
 * What the last plan-screen change did (POST /plans/replan's outcome): per-request results,
 * the changed meals with their reason, logged food, days now off target, warnings and notes.
 * Takes focus when it appears so the result is read out and scrolled into view.
 */
export function WhatChanged({
  outcome,
  today,
  onDismiss,
  onUndo,
  undoing = false,
}: {
  outcome: ChatOutcome;
  today: string;
  onDismiss: () => void;
  /** Shown when the change saved a version of an existing plan. */
  onUndo?: () => void;
  undoing?: boolean;
}) {
  const titleId = useId();
  const ref = useRef<HTMLElement>(null);
  const results = outcome.results ?? [];
  const changes = outcome.changes ?? [];
  const logged = outcome.logged ?? [];
  const offDays = (outcome.days ?? []).filter((d) => !d.within);
  const warnings = outcome.warnings ?? [];
  const notes = outcome.notes ?? [];
  const saved = outcome.plan_id != null;

  useEffect(() => {
    ref.current?.focus();
  }, [outcome]);

  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-labelledby={titleId}
      className="flex flex-col gap-2 rounded-xl border bg-card p-3 text-sm text-card-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id={titleId} className="flex items-center gap-1.5 font-medium">
          <CalendarCheckIcon aria-hidden className="size-4" />
          What changed
        </h2>
        <Button variant="ghost" size="icon-sm" aria-label="Dismiss" onClick={onDismiss}>
          <XIcon aria-hidden />
        </Button>
      </div>
      {outcome.fresh ? (
        <p className="text-muted-foreground">A new plan for this week was made first.</p>
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
            <li key={`${c.date}-${c.slot}`}>{changeLine(c, today)}</li>
          ))}
        </ul>
      ) : saved ? null : (
        <p className="text-muted-foreground">Your meals stay as they were.</p>
      )}
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
      {onUndo && saved && !outcome.fresh ? (
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          disabled={undoing}
          onClick={onUndo}
        >
          <Undo2Icon aria-hidden />
          Undo this change
        </Button>
      ) : null}
    </section>
  );
}
