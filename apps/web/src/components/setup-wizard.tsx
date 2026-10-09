"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { PantryAdd } from "@/components/pantry/pantry-add";
import { PantryList } from "@/components/pantry/pantry-list";
import { AllergiesForm } from "@/components/profile/allergies-form";
import { BodyForm } from "@/components/profile/body-form";
import { GoalsForm } from "@/components/profile/goals-form";
import { PreferencesForm } from "@/components/profile/preferences-form";
import { Button } from "@/components/ui/button";

export const STEPS = [
  { key: "body", title: "About you", optional: true },
  { key: "goals", title: "Your goals", optional: false },
  { key: "allergies", title: "Allergies", optional: false },
  { key: "preferences", title: "What you like", optional: false },
  { key: "pantry", title: "What's in your kitchen", optional: true },
] as const;

/** First-run setup, one short step per screen so it works one-handed on a phone. */
export function SetupWizard() {
  const router = useRouter();
  const [index, setIndex] = useState(0);
  const step = STEPS[index];
  const next = () => (index + 1 < STEPS.length ? setIndex(index + 1) : router.push("/plan"));

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground">
          Step {index + 1} of {STEPS.length}
        </p>
        <div className="flex gap-1" aria-hidden>
          {STEPS.map((s, i) => (
            <span
              key={s.key}
              className={`h-1 flex-1 rounded-full ${i <= index ? "bg-primary" : "bg-muted"}`}
            />
          ))}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{step.title}</h1>
      </div>

      {step.key === "body" && <BodyForm onSaved={next} />}
      {step.key === "goals" && <GoalsForm onSaved={next} />}
      {step.key === "allergies" && <AllergiesForm onSaved={next} />}
      {step.key === "preferences" && <PreferencesForm onSaved={next} />}
      {step.key === "pantry" && (
        <div className="flex flex-col gap-4">
          <PantryAdd />
          <PantryList />
          <Button onClick={next}>Done</Button>
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
