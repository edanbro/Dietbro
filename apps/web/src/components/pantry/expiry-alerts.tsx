"use client";

import { cn } from "cn";
import { ClockAlertIcon } from "lucide-react";

import { useExpiring } from "@/lib/api/hooks";

/** "expired 2 days ago", "expired yesterday", "use today", "expires tomorrow", "expires in 2 days". */
export function expiryText(daysLeft: number): string {
  if (daysLeft < -1) return `expired ${-daysLeft} days ago`;
  if (daysLeft === -1) return "expired yesterday";
  if (daysLeft === 0) return "use today";
  if (daysLeft === 1) return "expires tomorrow";
  return `expires in ${daysLeft} days`;
}

/** Pantry food that's expired or expires within 3 days, soonest first; nothing when none. */
export function ExpiryAlerts() {
  const { data } = useExpiring(3);
  if (!data?.items.length) return null;
  const soon = data.items.length - data.expired;
  const summary = [
    data.expired ? `${data.expired} expired` : null,
    soon ? `${soon} to use in the next ${data.days} days` : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <section
      aria-labelledby="expiry-alerts-title"
      className="flex flex-col gap-2 rounded-xl border border-amber-500/40 bg-amber-50 p-3 dark:bg-amber-950/30"
    >
      <div className="flex items-center gap-2">
        <ClockAlertIcon aria-hidden className="size-4 text-amber-700 dark:text-amber-400" />
        <h2 id="expiry-alerts-title" className="text-sm font-semibold">
          Use soon
        </h2>
        <span className="text-xs text-muted-foreground">{summary}</span>
      </div>
      <ul className="flex flex-col gap-1" aria-label="Expiring food">
        {data.items.map((item) => (
          <li key={item.id} className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate">{item.food.description}</span>
            <span
              className={cn(
                "shrink-0 text-xs",
                item.days_left < 0 ? "font-medium text-destructive" : "text-muted-foreground",
              )}
            >
              {expiryText(item.days_left)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
