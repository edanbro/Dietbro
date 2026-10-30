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
import {
  type RecentFood,
  type Slot,
  useFood,
  useLogFood,
  useParseFoodText,
  useRecentFoods,
} from "@/lib/api/hooks";
import { foodName } from "@/lib/food-name";
import { formatNumber } from "@/lib/format";

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
const RECENT = 6; // recent mixes offered to log again

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
 * rest of that day's plan rebalances around it.
 */
/** `initialSlot`: start open, logging for that meal (a link asked for it). */
export function QuickAdd({
  onDone,
  initialSlot = null,
}: {
  onDone?: () => void;
  initialSlot?: Slot | null;
}) {
  const [open, setOpen] = useState(initialSlot !== null);
  const [slot, setSlot] = useState<Slot>(() => initialSlot ?? slotNow());
  const [picked, setPicked] = useState<Picked[]>([]);
  const [typed, setTyped] = useState("");
  const log = useLogFood();
  const parse = useParseFoodText();
  const recent = useRecentFoods(open);

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

  /** A recent mix back in the form, at its amounts, to log as is or change first. */
  function again(r: RecentFood) {
    setPicked(
      r.items.map(({ food, grams }) => ({
        key: crypto.randomUUID(),
        id: food.id,
        description: food.description,
        brand: food.brand,
        image_url: food.image_url,
        quantity: String(grams),
        unit: "g",
        each: 1,
      })),
    );
  }

  /** What they typed, as foods in the form: to check and change before anything is logged. */
  function findTyped() {
    const text = typed.trim();
    if (!text) return;
    parse.mutate(text, {
      onSuccess: ({ items }) => {
        setPicked((p) => [
          ...p,
          ...items.map(({ food, grams }) => ({
            key: crypto.randomUUID(),
            id: food.id,
            description: food.description,
            brand: food.brand,
            image_url: food.image_url,
            quantity: String(grams),
            unit: "g",
            each: 1,
          })),
        ]);
        setTyped("");
      },
    });
  }

  function close() {
    setOpen(false);
    setPicked([]);
    setTyped("");
    log.reset();
    parse.reset();
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
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="quick-add-typed">Type what you had</Label>
        <div className="flex gap-2">
          <Input
            id="quick-add-typed"
            placeholder="2 eggs, toast and a coffee"
            maxLength={300}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault(); // find the foods, don't log the form
                findTyped();
              }
            }}
          />
          <Button
            type="button"
            variant="outline"
            disabled={!typed.trim() || parse.isPending}
            onClick={findTyped}
          >
            {parse.isPending ? "Finding�" : "Find"}
          </Button>
        </div>
        <ErrorAlert error={parse.error} />
        {parse.data?.items.some((i) => i.estimated) ? (
          <p className="text-xs text-muted-foreground">
            Where you gave no amount, that&apos;s a typical portion. Change any that look wrong.
          </p>
        ) : null}
        {parse.data?.unmatched.length ? (
          <p className="text-xs text-muted-foreground">
            Couldn&apos;t find {parse.data.unmatched.join(", ")}. Try searching below.
          </p>
        ) : null}
      </div>
      {!picked.length && recent.data?.length ? (
        <section aria-labelledby="quick-add-recent" className="flex flex-col gap-1.5">
          <h3 id="quick-add-recent" className="text-sm font-medium">
            Recent
          </h3>
          <ul className="flex flex-wrap gap-1.5">
            {recent.data.slice(0, RECENT).map((r) => (
              <li key={r.items.map((i) => `${i.food.id}x${i.grams}`).join(",")}>
                <button
                  type="button"
                  onClick={() => again(r)}
                  className="inline-flex h-9 max-w-64 items-center gap-1 rounded-full border px-3 text-sm hover:bg-muted"
                >
                  <span className="truncate">
                    {r.items.map((i) => foodName(i.food.description).name).join(" + ")}
                  </span>{" "}
                  <span className="shrink-0 text-xs text-muted-foreground">
                    · {formatNumber(r.kcal)} kcal
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
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
