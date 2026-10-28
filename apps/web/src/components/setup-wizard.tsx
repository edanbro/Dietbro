"use client";

import { cn } from "cn";
import { LoaderCircleIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorAlert } from "@/components/form-bits";
import { PantryAdd } from "@/components/pantry/pantry-add";
import { PantryList } from "@/components/pantry/pantry-list";
import { AllergiesForm } from "@/components/profile/allergies-form";
import { BodyForm } from "@/components/profile/body-form";
import { GoalsForm } from "@/components/profile/goals-form";
import { PreferencesForm } from "@/components/profile/preferences-form";
import { RegionForm } from "@/components/profile/region-form";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type Me, useCreatePlan, useCurrentPlan, useMe } from "@/lib/api/hooks";

export const STEPS = [
  { key: "region", title: "Where are you?", short: "Where", optional: false },
  { key: "body", title: "About you", short: "You", optional: true },
  { key: "goals", title: "Your goals", short: "Goals", optional: false },
  { key: "allergies", title: "Allergies", short: "Allergies", optional: false },
  { key: "preferences", title: "What you like", short: "Likes", optional: false },
  { key: "pantry", title: "What's in your kitchen", short: "Kitchen", optional: true },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

function done(me: Me, key: StepKey): boolean {
  switch (key) {
    case "region":
      return me.region.saved;
    case "body":
      return me.profile.has_body;
    case "goals":
      return me.profile.has_goals;
    case "allergies":
      return me.profile.has_allergies;
    case "preferences":
      return me.profile.has_preferences;
    case "pantry":
      return me.profile.pantry_items > 0;
  }
}

/**
 * Where to pick up: the first required step not done yet; with every required step done, the
 * last (kitchen) step, where the first plan is made. Skipped optional steps aren't revisited.
 */
export function resumeAt(me: Me): number {
  const i = STEPS.findIndex((s) => !s.optional && !done(me, s.key));
  return i === -1 ? STEPS.length - 1 : i;
}

/** The last step's way out: make the first plan (if there's none yet), or just finish. */
function Finish() {
  const router = useRouter();
  const plan = useCurrentPlan();
  const create = useCreatePlan();
  if (plan.isPending) return <Skeleton className="h-10" />;
  if (plan.data) {
    return <Button onClick={() => router.push("/plan")}>Go to my plan</Button>;
  }
  return (
    <div className="flex flex-col gap-2">
      <Button
        size="lg"
        disabled={create.isPending}
        aria-busy={create.isPending || undefined}
        onClick={() => create.mutate(undefined, { onSuccess: () => router.push("/plan") })}
      >
        {create.isPending ? (
          <>
            <LoaderCircleIcon aria-hidden className="animate-spin" />
            Planning your week…
          </>
        ) : (
          "Plan my first week"
        )}
      </Button>
      <ErrorAlert error={create.error} />
      <Button variant="ghost" disabled={create.isPending} onClick={() => router.push("/plan")}>
        Not now
      </Button>
    </div>
  );
}

function Wizard({ start }: { start: number }) {
  const router = useRouter();
  const [index, setIndex] = useState(start);
  const step = STEPS[index];
  const next = () => (index + 1 < STEPS.length ? setIndex(index + 1) : router.push("/plan"));

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <p className="text-xs text-muted-foreground">
          Step {index + 1} of {STEPS.length}
        </p>
        {/* Each step named under its bar; steps already done can be opened again. */}
        <ol className="grid grid-cols-6 gap-1" aria-label="Steps">
          {STEPS.map((s, i) => {
            const bar = (
              <>
                <span
                  aria-hidden
                  className={cn(
                    "h-1 w-full rounded-full transition-colors motion-reduce:transition-none",
                    i <= index ? "bg-primary" : "bg-muted",
                  )}
                />
                <span
                  className={cn(
                    "truncate text-xs",
                    i === index ? "font-medium text-foreground" : "text-muted-foreground",
                  )}
                >
                  {i < index ? <span className="sr-only">Back to </span> : null}
                  {s.short}
                </span>
              </>
            );
            return (
              <li key={s.key} aria-current={i === index ? "step" : undefined}>
                {i < index ? (
                  <button
                    type="button"
                    className="flex w-full flex-col items-start gap-1 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => setIndex(i)}
                  >
                    {bar}
                  </button>
                ) : (
                  <span className="flex flex-col items-start gap-1">{bar}</span>
                )}
              </li>
            );
          })}
        </ol>
        <h1 className="text-2xl font-semibold tracking-tight">{step.title}</h1>
      </div>

      {step.key === "region" && <RegionForm onSaved={next} />}
      {step.key === "body" && <BodyForm onSaved={next} />}
      {step.key === "goals" && <GoalsForm onSaved={next} />}
      {step.key === "allergies" && <AllergiesForm onSaved={next} />}
      {step.key === "preferences" && <PreferencesForm onSaved={next} />}
      {step.key === "pantry" && (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">
            Add what you already have, and plans use it up first. You can skip this.
          </p>
          <PantryAdd />
          {/* A first pantry is short: one search box (adding) is enough. */}
          <PantryList searchFrom={12} />
          <Finish />
        </div>
      )}

      <div className="flex justify-between">
        <Button variant="ghost" disabled={index === 0} onClick={() => setIndex(index - 1)}>
          Back
        </Button>
        {step.optional && step.key !== "pantry" ? (
          <Button variant="ghost" onClick={next}>
            Skip
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** First-run setup, one short step per screen so it works one-handed on a phone; it resumes
 * where it was left and ends by making the first plan. */
export function SetupWizard() {
  const me = useMe();
  if (me.isPending) {
    return (
      <div className="flex flex-col gap-3" aria-busy>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-48" />
      </div>
    );
  }
  if (me.error) return <ErrorAlert error={me.error} onRetry={() => void me.refetch()} />;
  return <Wizard start={resumeAt(me.data)} />;
}
