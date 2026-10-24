"use client";

import { MinusIcon, PlusIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

const MAX = 20;

/**
 * "− 2 servings +": `step` 0.5 moves in halves (cook mode); 1 moves to the next whole number
 * (2½ goes to 3 or 2), down to 1.
 */
export function ServingsStepper({
  value,
  onChange,
  step = 0.5,
}: {
  value: number;
  onChange: (servings: number) => void;
  step?: 0.5 | 1;
}) {
  const min = step === 1 ? 1 : 0.5;
  const fewer = Math.max(min, Math.ceil(value / step) * step - step);
  const more = Math.min(MAX, Math.floor(value / step) * step + step);
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Servings">
      <Button
        variant="outline"
        size="icon-sm"
        aria-label="Fewer servings"
        disabled={value <= min}
        onClick={() => onChange(fewer)}
      >
        <MinusIcon />
      </Button>
      <span className="w-24 text-center text-sm tabular-nums" aria-live="polite">
        {value} {value === 1 ? "serving" : "servings"}
      </span>
      <Button
        variant="outline"
        size="icon-sm"
        aria-label="More servings"
        disabled={value >= MAX}
        onClick={() => onChange(more)}
      >
        <PlusIcon />
      </Button>
    </div>
  );
}
