"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  ErrorAlert,
  fromNumber,
  LabeledInput,
  NativeSelect,
  NotMedicalAdvice,
  toNumber,
} from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { type GoalsIn, useBody, useGoals, useSaveGoals } from "@/lib/api/hooks";

type Goal = NonNullable<GoalsIn["goal"]>;
type FormState = {
  goal: Goal | "";
  kcal_min: string;
  kcal_max: string;
  protein_g_min: string;
  weekly_budget: string;
  currency: GoalsIn["currency"];
  calorie_floor: string;
};

const GOALS: { value: Goal; label: string }[] = [
  { value: "lose", label: "Lose weight slowly" },
  { value: "maintain", label: "Maintain" },
  { value: "gain", label: "Gain" },
];

/** Daily energy band (+ optional protein minimum) and a weekly food budget. */
export function GoalsForm({ onSaved }: { onSaved?: () => void }) {
  const { data: saved } = useGoals();
  const { data: body } = useBody();
  const save = useSaveGoals();
  const [form, setForm] = useState<FormState | null>(null);

  const current: FormState = form ?? {
    goal: saved?.goal ?? "",
    kcal_min: fromNumber(saved?.kcal_min),
    kcal_max: fromNumber(saved?.kcal_max),
    protein_g_min: fromNumber(saved?.protein_g_min),
    weekly_budget:
      saved?.weekly_budget_minor === null || saved?.weekly_budget_minor === undefined
        ? ""
        : String(saved.weekly_budget_minor / 100),
    currency: saved?.currency ?? "GBP",
    calorie_floor: fromNumber(saved?.calorie_floor ?? 1200),
  };
  const set = (patch: Partial<FormState>) => setForm({ ...current, ...patch });

  const suggestion = body && current.goal ? body.suggestions[current.goal] : undefined;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const budget = toNumber(current.weekly_budget);
    const payload: GoalsIn = {
      goal: current.goal || null,
      kcal_min: Number(current.kcal_min),
      kcal_max: Number(current.kcal_max),
      protein_g_min: toNumber(current.protein_g_min),
      weekly_budget_minor: budget === null ? null : Math.round(budget * 100),
      currency: current.currency,
      calorie_floor: toNumber(current.calorie_floor) ?? 1200,
      max_daily_deficit: saved?.max_daily_deficit ?? 1000,
    };
    save.mutate(payload, {
      onSuccess: () => {
        setForm(null);
        toast.success("Goals saved");
        onSaved?.();
      },
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Goals">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="goal">Goal</Label>
        <NativeSelect
          id="goal"
          value={current.goal}
          onChange={(e) => set({ goal: e.target.value as Goal | "" })}
        >
          <option value="">Choose…</option>
          {GOALS.map((g) => (
            <option key={g.value} value={g.value}>
              {g.label}
            </option>
          ))}
        </NativeSelect>
      </div>
      {suggestion ? (
        <div className="flex items-center justify-between gap-2 rounded-lg bg-muted p-3 text-sm">
          <span>
            Suggested: {suggestion.kcal_min}–{suggestion.kcal_max} kcal
            {suggestion.protein_g_min ? `, ≥ ${Math.round(suggestion.protein_g_min)} g protein` : ""}
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() =>
              set({
                kcal_min: String(suggestion.kcal_min),
                kcal_max: String(suggestion.kcal_max),
                protein_g_min: fromNumber(
                  suggestion.protein_g_min ? Math.round(suggestion.protein_g_min) : null,
                ),
              })
            }
          >
            Use
          </Button>
        </div>
      ) : null}
      <div className="grid grid-cols-2 gap-3">
        <LabeledInput
          id="kcal-min"
          label="Min kcal / day"
          type="number"
          inputMode="numeric"
          required
          value={current.kcal_min}
          onChange={(e) => set({ kcal_min: e.target.value })}
        />
        <LabeledInput
          id="kcal-max"
          label="Max kcal / day"
          type="number"
          inputMode="numeric"
          required
          value={current.kcal_max}
          onChange={(e) => set({ kcal_max: e.target.value })}
        />
      </div>
      <LabeledInput
        id="protein-min"
        label="Min protein (g / day, optional)"
        type="number"
        inputMode="numeric"
        value={current.protein_g_min}
        onChange={(e) => set({ protein_g_min: e.target.value })}
      />
      <div className="grid grid-cols-[1fr_6rem] gap-3">
        <LabeledInput
          id="budget"
          label="Weekly food budget (optional)"
          type="number"
          inputMode="decimal"
          step="0.01"
          value={current.weekly_budget}
          onChange={(e) => set({ weekly_budget: e.target.value })}
        />
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="currency">Currency</Label>
          <NativeSelect
            id="currency"
            value={current.currency}
            onChange={(e) => set({ currency: e.target.value as GoalsIn["currency"] })}
          >
            <option>GBP</option>
            <option>EUR</option>
            <option>USD</option>
          </NativeSelect>
        </div>
      </div>
      <LabeledInput
        id="floor"
        label="Calorie floor"
        hint="Plans never go below this. It can't be set under 1000 kcal."
        type="number"
        inputMode="numeric"
        value={current.calorie_floor}
        onChange={(e) => set({ calorie_floor: e.target.value })}
      />
      <ErrorAlert error={save.error} />
      <Button type="submit" disabled={save.isPending}>
        Save goals
      </Button>
      <NotMedicalAdvice />
    </form>
  );
}
