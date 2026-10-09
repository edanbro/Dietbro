"use client";

import { cn } from "cn";
import { AlertCircleIcon } from "lucide-react";
import type * as React from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/browser";

/** Native <select>: the platform picker is the best mobile UI for short lists. */
export function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-10 w-full rounded-lg border border-input bg-transparent px-2.5 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30",
        className,
      )}
      {...props}
    />
  );
}

export function LabeledInput({
  label,
  id,
  hint,
  ...props
}: React.ComponentProps<typeof Input> & { label: string; id: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} {...props} />
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/** Server-side problems (unsafe targets, bad units...) shown as a list. */
export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  const messages =
    error instanceof ApiError && error.messages.length ? error.messages : [String(error)];
  return (
    <Alert variant="destructive" role="alert">
      <AlertCircleIcon />
      <AlertDescription>
        <ul className="list-disc pl-4">
          {messages.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}

/** "" -> null, "12" -> 12, for optional numeric inputs. */
export function toNumber(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function fromNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

export function NotMedicalAdvice() {
  return (
    <p className="text-xs text-muted-foreground">
      Larder does planning arithmetic, not medical advice. Talk to a doctor or dietitian before
      big changes to how you eat.
    </p>
  );
}
