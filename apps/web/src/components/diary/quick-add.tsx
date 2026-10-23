"use client";

import { PlusIcon, XIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ProductThumb } from "@/components/food-bits";
import { FoodPicker } from "@/components/food-picker";
import { ErrorAlert, NativeSelect } from "@/components/form-bits";
import { BarcodeScan } from "@/components/pantry/barcode-scan";
import { SLOT_LABEL } from "@/components/plan/slots";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type Slot, useFood, useLogFood } from "@/lib/api/hooks";
import { foodName } from "@/lib/food-name";

type Picked = {
  key: string;
  id: number;
  description: string;
  brand?: string | null;
  image_url?: string | null;
  quantity: string;
  unit: string;
  each: number; // grams per unit
};

const SLOTS: Slot[] = ["breakfast", "lunch", "dinner", "snack"];

/** The meal a log most likely belongs to, by the clock. */
export function slotNow(d: Date = new Date()): Slot {
  const h = d.getHours();
  return h < 11 ? "breakfast" : h < 15 ? "lunch" : h < 21 ? "dinner" : "snack";
}

function label(f: Pick<Picked, "description" | "brand">): string {
  return f.brand ? `${f.brand} ${f.description}` : foodName(f.description).name;
}

/** One picked food: how much, in any unit we can weigh for it. Reports its grams. */
function PickedRow({
  item,
  onChange,
  onRemove,
}: {
  item: Picked;
  onChange: (next: Picked) => void;
  onRemove: () => void;
}) {
  const { data: detail } = useFood(item.id);
  const units = detail?.units ?? [];
  const name = label(item);
  return (
    <li className="flex items-center gap-2 py-2">
      <ProductThumb url={item.image_url ?? null} size={32} />
      <span className="min-w-0 flex-1 truncate text-sm">{name}</span>
      <Input
        type="number"
        inputMode="decimal"
        step="any"
        min="0"
        className="w-20"
        aria-label={`Amount of ${name}`}
        value={item.quantity}
        onChange={(e) => onChange({ ...item, quantity: e.target.value })}
      />
      <NativeSelect
        aria-label={`Unit for ${name}`}
        className="w-28"
        value={item.unit}
        onChange={(e) => {
          const unit = e.target.value;
          const each = gramsEach(unit, units);
          if (each) onChange({ ...item, unit, each });
        }}
      >
        {(units.length ? units : [{ unit: "g", grams_each: 1 }]).map((u) => (
          <option key={u.unit} value={u.unit}>
            {u.unit}
          </option>
        ))}
      </NativeSelect>
      <Button variant="ghost" size="icon" aria-label={`Remove ${name}`} onClick={onRemove}>
        <XIcon />
      </Button>
    </li>
  );
}

/** Grams in one `unit` of a food, from its units (grams and kilograms always work). */
export function gramsEach(
  unit: string,
  units: { unit: string; grams_each?: number | null }[],
): number | null {
  if (unit === "g") return 1;
  if (unit === "kg") return 1000;
  return units.find((u) => u.unit === unit)?.grams_each ?? null;
}

/**
 * Log food you ate that wasn't on the plan: search or scan, say how much, pick the meal. The
 * rest of that day's plan rebalances around it, exactly as when you tell the chat.
 */
export function QuickAdd({ onDone }: { onDone?: () => void }) {
  const [open, setOpen] = useState(false);
  const [slot, setSlot] = useState<Slot>(() => slotNow());
  const [picked, setPicked] = useState<Picked[]>([]);
  const log = useLogFood();

  function add(f: { id: number; description: string; brand?: string | null; image_url?: string | null }) {
    setPicked((p) => [
      ...p,
      {
        key: crypto.randomUUID(),
        id: f.id,
        description: f.description,
        brand: f.brand,
        image_url: f.image_url,
        quantity: "100",
        unit: "g",
        each: 1,
      },
    ]);
  }

  function close() {
    setOpen(false);
    setPicked([]);
    log.reset();
  }

  if (!open) {
    return (
      <Button variant="outline" onClick={() => setOpen(true)}>
        <PlusIcon aria-hidden />
        Add food
      </Button>
    );
  }

  const items = picked.map((p) => ({ food_id: p.id, grams: Number(p.quantity) * p.each }));
  const ready = picked.length > 0 && items.every((i) => Number.isFinite(i.grams) && i.grams > 0);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    log.mutate(
      { items: items.map((i) => ({ ...i, grams: Math.round(i.grams * 10) / 10 })), slot },
      {
        onSuccess: (outcome) => {
          const message = outcome.results?.[0]?.message;
          toast.success(message ?? "Logged");
          close();
          onDone?.();
        },
      },
    );
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Add food you ate"
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Add food you ate</h2>
        <Button type="button" variant="ghost" size="icon" aria-label="Close" onClick={close}>
          <XIcon />
        </Button>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="quick-add-slot">Meal</Label>
        <NativeSelect
          id="quick-add-slot"
          value={slot}
          onChange={(e) => setSlot(e.target.value as Slot)}
        >
          {SLOTS.map((s) => (
            <option key={s} value={s}>
              {SLOT_LABEL[s]}
            </option>
          ))}
        </NativeSelect>
      </div>
      <FoodPicker id="quick-add-search" placeholder="Search foods, e.g. banana" onPick={add} />
      <BarcodeScan onFound={add} />
      {picked.length ? (
        <ul className="flex flex-col divide-y" aria-label="Foods to log">
          {picked.map((p) => (
            <PickedRow
              key={p.key}
              item={p}
              onChange={(next) => setPicked((all) => all.map((x) => (x.key === p.key ? next : x)))}
              onRemove={() => setPicked((all) => all.filter((x) => x.key !== p.key))}
            />
          ))}
        </ul>
      ) : null}
      <ErrorAlert error={log.error} />
      <Button type="submit" disabled={!ready || log.isPending}>
        {log.isPending ? "Logging…" : "Log it"}
      </Button>
      <p className="text-xs text-muted-foreground">
        Counts toward the day; the rest of that day&apos;s plan adjusts around it.
      </p>
    </form>
  );
}
