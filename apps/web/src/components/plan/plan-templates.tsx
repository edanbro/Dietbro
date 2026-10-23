"use client";

import {
  BookmarkPlusIcon,
  CopyIcon,
  HistoryIcon,
  LayoutTemplateIcon,
  LoaderCircleIcon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, NativeSelect } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type CreatePlanArgs,
  type Plan,
  type PlanChange,
  type PlanDay,
  type useCreatePlan,
  useMealsOn,
  useSaveTemplate,
  useTemplates,
} from "@/lib/api/hooks";
import { addDays, longDate, weekday } from "@/lib/dates";

import { SLOT_LABEL } from "./slots";

type CreatePlan = ReturnType<typeof useCreatePlan>;

/**
 * Ways to make the new plan, beside a fresh one: the same meals as last week (the same
 * weekdays), or a saved template. Meals that no longer suit the user's allergies, diet or
 * blocks are left out by the server, which says so in the plan's notes.
 */
export function RepeatChoices({
  today,
  create,
  onCreated,
}: {
  today: string;
  create: CreatePlan;
  onCreated: () => void;
}) {
  const templates = useTemplates();
  const [picked, setPicked] = useState<string>("");
  const run = (args: CreatePlanArgs) => create.mutate(args, { onSuccess: onCreated });
  const list = templates.data ?? [];
  const chosen = picked || (list[0] ? String(list[0].id) : "");
  return (
    <div className="flex flex-col gap-2">
      <Button
        variant="outline"
        size="sm"
        className="self-start"
        disabled={create.isPending}
        onClick={() => run({ repeat_from: addDays(today, -7) })}
      >
        <HistoryIcon aria-hidden />
        Repeat last week
      </Button>
      {list.length ? (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="plan-template" className="sr-only">
            Template
          </label>
          <NativeSelect
            id="plan-template"
            value={chosen}
            onChange={(e) => setPicked(e.target.value)}
            className="max-w-56"
          >
            {list.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </NativeSelect>
          <Button
            variant="outline"
            size="sm"
            disabled={create.isPending || !chosen}
            onClick={() => run({ template_id: Number(chosen) })}
          >
            <LayoutTemplateIcon aria-hidden />
            Use template
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** "Save as template": names this week's meals so they can be planned again. */
export function SaveTemplate({ plan }: { plan: Plan }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const save = useSaveTemplate();
  if (!open) {
    return (
      <Button variant="ghost" onClick={() => setOpen(true)}>
        <BookmarkPlusIcon aria-hidden />
        {/* "Save" on phones; "Save as template" everywhere else and to screen readers. */}
        Save <span className="max-sm:sr-only">as template</span>
      </Button>
    );
  }
  return (
    <form
      aria-label="Save as template"
      className="flex w-full flex-wrap items-center gap-2 rounded-lg border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(
          { name: name.trim(), start: plan.start },
          {
            onSuccess: (t) => {
              toast.success(`Saved "${t.name}": plan it again from New plan`);
              setOpen(false);
              setName("");
            },
          },
        );
      }}
    >
      <label htmlFor="template-name" className="text-sm font-medium">
        Template name
      </label>
      <Input
        id="template-name"
        required
        maxLength={60}
        placeholder="e.g. Busy weeknights"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="min-w-40 flex-1"
        autoFocus
      />
      <Button type="submit" size="sm" disabled={save.isPending || !name.trim()}>
        {save.isPending ? <LoaderCircleIcon aria-hidden className="animate-spin" /> : null}
        Save
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
        Cancel
      </Button>
      <div className="w-full">
        <ErrorAlert error={save.error} />
      </div>
    </form>
  );
}

/**
 * Copy another day's meals onto `day` ("same as last Tuesday"): pick a date, see its meals,
 * and each one replaces that slot here (a swap to that recipe, checked like any other).
 */
export function CopyDay({
  day,
  today,
  busy,
  onReplan,
}: {
  day: PlanDay;
  today: string;
  busy: boolean;
  onReplan: (changes: PlanChange[]) => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(() => addDays(day.date, -7));
  const meals = useMealsOn(from, open);
  // Only slots still to eat here change; an eaten meal stays as it was.
  const free = day.meals.filter((m) => m.status !== "eaten").map((m) => m.slot);
  const copies = (meals.data ?? []).filter((m) => free.includes(m.slot));

  if (!open) {
    return (
      <Button
        variant="outline"
        size="sm"
        className="self-start"
        disabled={busy}
        onClick={() => setOpen(true)}
      >
        <CopyIcon aria-hidden />
        Copy another day
      </Button>
    );
  }
  return (
    <div
      role="group"
      aria-label={`Copy meals to ${weekday(day.date)}`}
      className="flex flex-col gap-3 rounded-lg border p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={`copy-from-${day.date}`} className="text-sm font-medium">
          Use the meals from
        </label>
        <Input
          id={`copy-from-${day.date}`}
          type="date"
          value={from}
          max={addDays(today, 13)}
          onChange={(e) => setFrom(e.target.value)}
          className="w-auto"
        />
      </div>
      {meals.isPending ? (
        <p className="text-sm text-muted-foreground">Looking…</p>
      ) : copies.length ? (
        <ul className="flex flex-col gap-1 text-sm" aria-label={`Meals on ${longDate(from)}`}>
          {copies.map((m) => (
            <li key={m.slot}>
              <span className="text-muted-foreground">{SLOT_LABEL[m.slot]}:</span> {m.recipe.name}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No meals planned on {longDate(from)}.</p>
      )}
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={busy || !copies.length}
          onClick={() =>
            void onReplan(
              copies.map((m) => ({
                intent: "swap" as const,
                when: { date: day.date, slot: m.slot },
                recipe_id: m.recipe.id,
              })),
            )
              .then(() => setOpen(false))
              .catch(() => undefined)
          }
        >
          Use these meals
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      <ErrorAlert error={meals.error} />
    </div>
  );
}
