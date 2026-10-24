"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, LabeledInput, NativeSelect, NotMedicalAdvice } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  type BodyIn,
  type BodyOut,
  useBody,
  useDeleteBody,
  useSaveBody,
  useUnits,
} from "@/lib/api/hooks";
import { bodyWeight, cmFrom, feetInches, kgFrom } from "@/lib/units";

// The form as typed: height in cm, or feet and inches; weight in kg or lb (the user's units).
type Fields = {
  sex: string;
  age: string;
  activity: string;
  cm: string;
  feet: string;
  inches: string;
  weight: string;
};

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
  const units = useUnits();
  const us = units === "us";
  const [form, setForm] = useState<Fields | null>(null);

  const [feet, inches] = saved ? feetInches(saved.height_cm) : [null, null];
  const current: Fields = form ?? {
    sex: saved?.sex ?? "female",
    age: saved ? String(saved.age) : "",
    activity: saved?.activity ?? "light",
    cm: saved ? String(saved.height_cm) : "",
    feet: feet === null ? "" : String(feet),
    inches: inches === null ? "" : String(inches),
    weight: saved ? String(bodyWeight(saved.weight_kg, units)) : "",
  };
  const set = (key: keyof Fields) => (value: string) => setForm({ ...current, [key]: value });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const payload: BodyIn = {
      sex: current.sex as BodyIn["sex"],
      age: Number(current.age),
      height_cm: us
        ? cmFrom(Number(current.feet), Number(current.inches || 0))
        : Number(current.cm),
      weight_kg: kgFrom(Number(current.weight), units),
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
      <div className={us ? "grid grid-cols-2 gap-3" : "grid grid-cols-3 gap-3"}>
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
        {us ? null : (
          <LabeledInput
            id="height"
            label="Height (cm)"
            inputMode="decimal"
            type="number"
            min={120}
            max={250}
            required
            value={current.cm}
            onChange={(e) => set("cm")(e.target.value)}
          />
        )}
        <LabeledInput
          id="weight"
          label={us ? "Weight (lb)" : "Weight (kg)"}
          inputMode="decimal"
          type="number"
          step="0.1"
          min={us ? 66 : 30}
          max={us ? 770 : 350}
          required
          value={current.weight}
          onChange={(e) => set("weight")(e.target.value)}
        />
        {us ? (
          <>
            <LabeledInput
              id="height-ft"
              label="Height (ft)"
              inputMode="numeric"
              type="number"
              min={4}
              max={8}
              required
              value={current.feet}
              onChange={(e) => set("feet")(e.target.value)}
            />
            <LabeledInput
              id="height-in"
              label="and inches"
              inputMode="numeric"
              type="number"
              min={0}
              max={11}
              value={current.inches}
              onChange={(e) => set("inches")(e.target.value)}
            />
          </>
        ) : null}
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
