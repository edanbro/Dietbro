"use client";

import { ChevronRightIcon, NotebookPenIcon } from "lucide-react";
import Link from "next/link";

import { useDiary } from "@/lib/api/hooks";

import { eatenText } from "./diary-page";

/** One line on the plan screen: what's been eaten today against the goal, linking the diary. */
export function TodaySummary() {
  const { data } = useDiary(7);
  if (!data) return null;
  const today = data.days.at(-1);
  return (
    <Link
      href="/diary"
      className="flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors hover:bg-muted/50"
    >
      <NotebookPenIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="font-medium">
          {eatenText(today?.eaten.kcal ?? 0, data.kcal_min, data.kcal_max)} today
        </span>
        {data.logged_days ? (
          <span className="text-xs text-muted-foreground">
            On target {data.on_target_days} of {data.logged_days} logged days this week
          </span>
        ) : null}
      </span>
      <span className="flex items-center text-xs text-muted-foreground">
        Diary
        <ChevronRightIcon aria-hidden className="size-4" />
      </span>
    </Link>
  );
}
