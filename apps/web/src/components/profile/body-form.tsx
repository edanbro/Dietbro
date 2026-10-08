"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, LabeledInput, NativeSelect, NotMedicalAdvice } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { type BodyIn, type BodyOut, useBody, useDeleteBody, useSaveBody } from "@/lib/api/hooks";

const ACTIVITY: { value: BodyIn["activity"]; label: string }[] = [
  { value: "sedentary", label: "Mostly sitting" },
  { value: "light", label: "Light exercise 1–3 days/week" },
  { value: "moderate", label: "Moderate exercise 3–5 days/week" },
  { value: "active", label: "Hard exercise 6–7 days/week" },
  { value: "very_active", label: "Physical job or training twice a day" },
];

/** Optional body stats: used only to estimate daily energy needs and check targets. */
export function BodyForm({ onSaved }: { onSaved?: (body: BodyOut) => void }) {
  const { data: saved } = useBody();
  const save = useSaveBody();
  const remove = useDeleteBody();
  const [form, setForm] = useState<Record<keyof BodyIn, string> | null>(null);

  const current = form ?? {
    sex: saved?.sex ?? "female",
    age: saved ? String(saved.age) : "",
    height_cm: saved ? String(saved.height_cm) : "",
    weight_kg: saved ? String(saved.weight_kg) : "",
    activity: saved?.activity ?? "light",
  };
  const set = (key: keyof BodyIn) => (value: string) => setForm({ ...current, [key]: value });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const payload: BodyIn = {
      sex: current.sex as BodyIn["sex"],
      age: Number(current.age),
      height_cm: Number(current.height_cm),
      weight_kg: Number(current.weight_kg),
      activity: current.activity as BodyIn["activity"],
    };
    save.mutate(payload, {
      onSuccess: (body) => {
        setForm(null);
        toast.success(`Estimated needs: ${body.tdee_kcal} kcal/day`);
        onSaved?.(body);
      },
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Body stats">
      <p className="text-sm text-muted-foreground">
        Optional. Used only to estimate how much energy you need per day and to keep calorie
        targets safe. Never shared.
      </p>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="sex">Sex (for the energy equation)</Label>
        <NativeSelect id="sex" value={current.sex} onChange={(e) => set("sex")(e.target.value)}>
          <option value="female">Female</option>
          <option value="male">Male</option>
        </NativeSelect>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <LabeledInput
          id="age"
          label="Age"
          inputMode="numeric"
          type="number"
          min={18}
          max={110}
          required
          value={current.age}
          onChange={(e) => set("age")(e.target.value)}
        />
        <LabeledInput
          id="height"
          label="Height (cm)"
          inputMode="decimal"
          type="number"
          min={120}
          max={250}
          required
          value={current.height_cm}
          onChange={(e) => set("height_cm")(e.target.value)}
        />
        <LabeledInput
          id="weight"
          label="Weight (kg)"
          inputMode="decimal"
          type="number"
          step="0.1"
          min={30}
          max={350}
          required
          value={current.weight_kg}
          onChange={(e) => set("weight_kg")(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="activity">Activity</Label>
        <NativeSelect
          id="activity"
          value={current.activity}
          onChange={(e) => set("activity")(e.target.value)}
        >
          {ACTIVITY.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </NativeSelect>
      </div>
      {saved ? (
        <p className="text-sm">
          Estimated needs: <strong>{saved.tdee_kcal} kcal/day</strong>
        </p>
      ) : null}
      <ErrorAlert error={save.error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          Save
        </Button>
        {saved ? (
          <Button
            type="button"
            variant="ghost"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(undefined, {
                onSuccess: () => {
                  setForm(null);
                  toast("Body stats removed");
                },
              })
            }
          >
            Remove my stats
          </Button>
        ) : null}
      </div>
      <NotMedicalAdvice />
    </form>
  );
}
