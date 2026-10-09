"use client";

import { cn } from "cn";
import {
  InfoIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  ShoppingBasketIcon,
  TriangleAlertIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api/browser";
import {
  type Plan,
  useAllergens,
  useCreatePlan,
  useCurrentPlan,
  useMe,
  type Violation,
} from "@/lib/api/hooks";
import {
  dateRange,
  dayOfMonth,
  daysBetween,
  localISODate,
  longDate,
  monthName,
  weekday,
} from "@/lib/dates";
import { allergenLabel, humanize } from "@/lib/format";

import { DayMacros } from "./macro-bars";
import { MealCard } from "./meal-card";
import { SLOT_ORDER } from "./slots";
import { WeekGrid } from "./week-grid";
import { WeekSummary } from "./week-summary";

type View = "day" | "week";
type CreatePlan = ReturnType<typeof useCreatePlan>;

/** Day and view live in the URL (?day=YYYY-MM-DD&view=week) so Back from a recipe returns here. */
function useViewState() {
  const params = useSearchParams();
  const router = useRouter();
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    router.replace(qs ? `/plan?${qs}` : "/plan", { scroll: false });
  };
  return {
    view: (params.get("view") === "week" ? "week" : "day") as View,
    day: params.get("day"),
    set,
  };
}

/** Whether the plan's last day is before today. */
export function planEnded(plan: Pick<Plan, "start" | "days">, today: string): boolean {
  return daysBetween(plan.start, today) >= plan.days.length;
}

function PlanSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy>
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-12" />
      <Skeleton className="h-20" />
      <Skeleton className="h-20" />
      <Skeleton className="h-20" />
    </div>
  );
}

function CreateError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="flex flex-col gap-2">
      <ErrorAlert error={error} />
      {error instanceof ApiError && error.status === 409 ? (
        <Link href="/profile" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
          Review your profile
        </Link>
      ) : null}
    </div>
  );
}

function PlanButton({
  create,
  onCreated,
  children,
  ...props
}: React.ComponentProps<typeof Button> & { create: CreatePlan; onCreated: () => void }) {
  return (
    <Button
      {...props}
      disabled={create.isPending}
      aria-busy={create.isPending || undefined}
      onClick={() => create.mutate(undefined, { onSuccess: onCreated })}
    >
      {create.isPending ? (
        <>
          <LoaderCircleIcon aria-hidden className="animate-spin" />
          Planning…
        </>
      ) : (
        children
      )}
    </Button>
  );
}

function PlanningStatus({ pending }: { pending: boolean }) {
  return (
    // Always mounted so screen readers announce the change; out of the layout when idle.
    <p role="status" className={pending ? "text-xs text-muted-foreground" : "sr-only"}>
      {pending ? "Planning your week. This takes a few seconds." : ""}
    </p>
  );
}

/** The plan screen: setup nudge, first plan, or the current plan. */
export function PlanPage() {
  const me = useMe();
  const plan = useCurrentPlan();
  const create = useCreatePlan();
  const { set } = useViewState();

  const onCreated = () => {
    set({ day: null, view: null });
    toast.success("Your week is planned");
  };

  if (me.isPending || (me.data?.setup_complete && plan.isPending)) return <PlanSkeleton />;
  if (me.error) return <ErrorAlert error={me.error} />;

  if (!me.data.setup_complete) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Your week</h1>
        <Alert>
          <AlertDescription className="flex items-center justify-between gap-2">
            Finish setting up so Larder can plan for you.
            <Link href="/setup" className={buttonVariants({ size: "sm" })}>
              Set up
            </Link>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  if (plan.error) return <ErrorAlert error={plan.error} />;

  if (!plan.data) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Your week</h1>
        <Card>
          <CardHeader>
            <CardTitle>No plan yet</CardTitle>
            <CardDescription>
              Larder plans breakfast, lunch and dinner for seven days around your goals, your
              allergies and what&apos;s already in your kitchen.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <PlanButton create={create} onCreated={onCreated} size="lg">
              Plan my week
            </PlanButton>
            <PlanningStatus pending={create.isPending} />
            <CreateError error={create.error} />
          </CardContent>
        </Card>
      </div>
    );
  }

  return <PlanView plan={plan.data} create={create} onCreated={onCreated} />;
}

function Exclusions({ plan }: { plan: Plan }) {
  const { data: options } = useAllergens();
  const labels = [
    ...plan.excluded_allergens.map((a) => allergenLabel(a, options)),
    ...(plan.diet ? [humanize(plan.diet)] : []),
  ];
  if (!labels.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span id="planned-without" className="text-muted-foreground">
        Planned without:
      </span>
      <ul aria-labelledby="planned-without" className="flex flex-wrap gap-1.5">
        {labels.map((l) => (
          <li key={l}>
            <Badge variant="secondary">{l}</Badge>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ViolationList({ items }: { items: Violation[] }) {
  return (
    <ul className="list-disc pl-4">
      {items.map((v, i) => (
        <li key={`${v.code}-${v.day}-${v.slot}-${i}`}>{v.message}</li>
      ))}
    </ul>
  );
}

/** What the plan misses (hard: only the quick planner; soft: trade-offs) and how it was made. */
function PlanNotes({ plan }: { plan: Plan }) {
  const hard = plan.violations.filter((v) => v.hard);
  const soft = plan.violations.filter((v) => !v.hard);
  const greedy = plan.planner === "greedy";
  return (
    <>
      {hard.length ? (
        <Alert
          role="note"
          data-testid="hard-violations"
          className="border-amber-500/50 bg-amber-50 text-amber-950 dark:bg-amber-950/30 dark:text-amber-100"
        >
          <TriangleAlertIcon aria-hidden />
          <AlertTitle>Quick planner couldn&apos;t meet:</AlertTitle>
          <AlertDescription className="text-current">
            <ViolationList items={hard} />
          </AlertDescription>
        </Alert>
      ) : null}
      {soft.length ? (
        <Alert role="note" data-testid="soft-violations">
          <InfoIcon aria-hidden />
          <AlertTitle>Trade-offs in this plan</AlertTitle>
          <AlertDescription>
            <ViolationList items={soft} />
          </AlertDescription>
        </Alert>
      ) : null}
      {greedy || plan.notes.length ? (
        <div
          data-testid="planner-note"
          className="flex flex-col gap-1 text-xs text-muted-foreground"
        >
          {greedy ? (
            <p>Made by the quick planner: fast, but it can miss a target now and then.</p>
          ) : null}
          {plan.notes.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </div>
      ) : null}
    </>
  );
}

function PlanView({
  plan,
  create,
  onCreated,
}: {
  plan: Plan;
  create: CreatePlan;
  onCreated: () => void;
}) {
  const { view, day, set } = useViewState();
  const [confirming, setConfirming] = useState(false);
  const today = localISODate();
  const ended = planEnded(plan, today);
  const first = plan.days[0]?.date ?? plan.start;
  const last = plan.days.at(-1)?.date ?? plan.start;
  const dates = plan.days.map((d) => d.date);
  const selected =
    day && dates.includes(day) ? day : dates.includes(today) ? today : (dates[0] ?? "");

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col">
        <h1 className="text-2xl font-semibold tracking-tight">Your week</h1>
        <p className="text-sm text-muted-foreground">{dateRange(first, last)}</p>
      </div>
      <div className="flex gap-2">
        <Link
          href="/plan/shopping"
          className={cn(buttonVariants({ variant: "outline" }), "flex-1")}
        >
          <ShoppingBasketIcon aria-hidden />
          Shopping list
        </Link>
        {ended ? null : (
          <Button
            variant="outline"
            className="flex-1"
            aria-expanded={confirming}
            aria-controls="new-plan-confirm"
            disabled={create.isPending}
            onClick={() => setConfirming(!confirming)}
          >
            <RefreshCwIcon aria-hidden />
            New plan
          </Button>
        )}
      </div>

      {confirming && !ended ? (
        <div
          id="new-plan-confirm"
          role="group"
          aria-label="Confirm new plan"
          className="flex flex-col gap-3 rounded-lg border p-3"
        >
          <p className="text-sm">Replaces this plan. Shopping ticks reset.</p>
          <div className="flex gap-2">
            <PlanButton
              create={create}
              size="sm"
              onCreated={() => {
                setConfirming(false);
                onCreated();
              }}
            >
              Replace plan
            </PlanButton>
            <Button
              size="sm"
              variant="ghost"
              disabled={create.isPending}
              onClick={() => setConfirming(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {ended ? (
        <Alert role="note">
          <InfoIcon aria-hidden />
          <AlertTitle>This plan ended on {longDate(last)}</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            Make a fresh plan for the week ahead.
            <PlanButton create={create} size="sm" onCreated={onCreated}>
              Plan this week
            </PlanButton>
          </AlertDescription>
        </Alert>
      ) : null}

      <PlanningStatus pending={create.isPending} />
      <CreateError error={create.error} />
      <Exclusions plan={plan} />
      <PlanNotes plan={plan} />

      <Tabs value={view} onValueChange={(v: View) => set({ view: v === "week" ? "week" : null })}>
        <TabsList className="w-full" aria-label="View">
          <TabsTrigger value="day">Day</TabsTrigger>
          <TabsTrigger value="week">Week</TabsTrigger>
        </TabsList>

        <TabsContent value="day" className="flex flex-col gap-4 pt-2">
          <Tabs value={selected} onValueChange={(d: string) => set({ day: d })}>
            <TabsList
              variant="line"
              aria-label="Day"
              className="grid h-auto w-full grid-cols-7 gap-1 p-0"
            >
              {plan.days.map((d) => (
                <TabsTrigger
                  key={d.date}
                  value={d.date}
                  className="h-auto flex-col gap-0 rounded-lg py-1.5 data-active:bg-muted"
                >
                  {/* Named by its visible text plus the month: "Fri 9 October". */}
                  <span className="text-[0.7rem] font-normal">
                    {d.date === today ? "Today" : weekday(d.date)}
                  </span>{" "}
                  <span className="text-base tabular-nums">{dayOfMonth(d.date)}</span>{" "}
                  <span className="sr-only">{monthName(d.date)}</span>
                </TabsTrigger>
              ))}
            </TabsList>
            {plan.days.map((d) => {
              const meals = [...d.meals].sort(
                (a, b) => SLOT_ORDER.indexOf(a.slot) - SLOT_ORDER.indexOf(b.slot),
              );
              return (
                <TabsContent key={d.date} value={d.date} className="flex flex-col gap-4 pt-2">
                  <ul aria-label={`Meals on ${longDate(d.date)}`} className="flex flex-col gap-2">
                    {meals.map((m) => (
                      <li key={m.slot}>
                        <MealCard meal={m} />
                      </li>
                    ))}
                  </ul>
                  <DayMacros totals={d.totals} bands={plan.targets.daily} />
                </TabsContent>
              );
            })}
          </Tabs>
        </TabsContent>

        <TabsContent value="week" className="pt-2">
          <WeekGrid days={plan.days} today={today} onPickDay={(d) => set({ day: d, view: null })} />
        </TabsContent>
      </Tabs>

      <WeekSummary plan={plan} />
    </div>
  );
}
