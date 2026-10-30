"use client";

import { cn } from "cn";
import { CalendarSyncIcon, ChefHatIcon, ClockAlertIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button, buttonVariants } from "@/components/ui/button";
import { useCreatePlan, useExpiring } from "@/lib/api/hooks";
import { displayName, foodNoun } from "@/lib/food-name";

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
      className="flex flex-col gap-2 rounded-xl border border-warning/50 bg-warning-subtle p-3 text-warning-subtle-foreground"
    >
      <div className="flex items-center gap-2">
        <ClockAlertIcon aria-hidden className="size-4 text-warning" />
        <h2 id="expiry-alerts-title" className="text-sm font-semibold">
          Use soon
        </h2>
        <span className="text-xs text-muted-foreground">{summary}</span>
      </div>
      <ul className="flex flex-col gap-1" aria-label="Expiring food">
        {data.items.map((item) => (
          <li key={item.id} className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate">
              {displayName(item.food.description, item.food.brand)}
            </span>
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
      <ExpiryActions names={data.items.map((i) => i.food.description)} />
    </section>
  );
}

/** The recipes that use them (a search for their names among what the pantry can make; it
 * works without the AI too), or re-plan the week from today around them (the planner already
 * favours food that expires soon). */
function ExpiryActions({ names }: { names: string[] }) {
  const router = useRouter();
  const create = useCreatePlan();
  const words = [...new Set(names.slice(0, 5).map(foodNoun))].join(" ");
  return (
    <div className="flex flex-wrap gap-2 pt-1">
      <Link
        href={`/recipes?pantry=1&q=${encodeURIComponent(words)}`}
        className={buttonVariants({ size: "sm", variant: "outline" })}
      >
        <ChefHatIcon aria-hidden />
        What can I make?
      </Link>
      <Button
        size="sm"
        variant="outline"
        disabled={create.isPending}
        onClick={() =>
          create.mutate(undefined, {
            onSuccess: () => {
              toast.success("Re-planned from today, using what expires first");
              router.push("/plan");
            },
          })
        }
      >
        <CalendarSyncIcon aria-hidden />
        {create.isPending ? "Planning…" : "Re-plan around these"}
      </Button>
    </div>
  );
}
