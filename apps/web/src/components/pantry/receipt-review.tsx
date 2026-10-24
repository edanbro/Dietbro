"use client";

import { cn } from "cn";
import {
  CircleAlertIcon,
  LoaderCircleIcon,
  PencilIcon,
  Trash2Icon,
  Undo2Icon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { FoodPicker } from "@/components/food-picker";
import { ErrorAlert, LabeledInput, NativeSelect } from "@/components/form-bits";
import { BackLink, plural } from "@/components/pantry/receipt-bits";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api/browser";
import {
  isReading,
  type Receipt,
  type ReceiptLine,
  type ReceiptLinePatch,
  useConfirmReceipt,
  useDeleteReceipt,
  useFood,
  useReceipt,
  useUpdateReceiptLine,
} from "@/lib/api/hooks";
import { shortDate } from "@/lib/dates";
import { displayName } from "@/lib/food-name";

/** How long to wait for the worker before saying something is wrong. */
export const GIVE_UP_MS = 60_000;

/** A line goes into the pantry on confirm when it has a food and wasn't rejected. */
export function willAdd(line: ReceiptLine): boolean {
  return line.food !== null && line.status !== "rejected";
}

/** "2 large · 300 g", "1.5 kg", or "" when the amount is unknown. */
export function lineAmount(line: ReceiptLine): string {
  if (line.quantity === null || line.unit === null) {
    return line.grams === null ? "" : `${Math.round(line.grams)} g`;
  }
  const q = line.quantity % 1 ? Number(line.quantity.toFixed(2)) : line.quantity;
  const grams = line.unit === "g" || line.grams === null ? "" : ` · ${Math.round(line.grams)} g`;
  return `${q} ${line.unit}${grams}`;
}

function lineLabel(line: ReceiptLine): string {
  return line.food?.description ?? line.name;
}

// --- editing one line --------------------------------------------------------------------------

function LineEditor({
  line,
  receiptId,
  onDone,
}: {
  line: ReceiptLine;
  receiptId: number;
  onDone: () => void;
}) {
  const update = useUpdateReceiptLine(receiptId);
  const [picking, setPicking] = useState(line.food === null);
  const [quantity, setQuantity] = useState(line.quantity === null ? "" : String(line.quantity));
  const [unit, setUnit] = useState(line.unit ?? "g");
  const [expires, setExpires] = useState(line.expires_on ?? "");
  const [approx, setApprox] = useState(line.approx);
  const { data: detail } = useFood(line.food?.id ?? null);

  const units = detail?.units.map((u) => u.unit) ?? [];
  const unitOptions = units.includes(unit) ? units : [unit, ...units];
  const label = lineLabel(line);

  function pickFood(food: { id: number }) {
    update.mutate(
      { lineId: line.id, patch: { food_id: food.id } },
      { onSuccess: () => setPicking(false) },
    );
  }

  function save(e: React.FormEvent) {
    e.preventDefault();
    const patch: ReceiptLinePatch = {};
    const q = Number(quantity);
    if (quantity !== "" && (q !== line.quantity || unit !== line.unit)) {
      patch.quantity = q;
      patch.unit = unit;
    }
    if (expires !== (line.expires_on ?? "")) patch.expires_on = expires || null;
    // A new amount counts as exact on the server unless approx is sent with it.
    if (approx !== line.approx || patch.quantity !== undefined) patch.approx = approx;
    if (!Object.keys(patch).length) {
      onDone();
      return;
    }
    update.mutate({ lineId: line.id, patch }, { onSuccess: onDone });
  }

  if (picking || line.food === null) {
    return (
      <div className="flex flex-col gap-2 pt-2">
        <FoodPicker
          id={`line-${line.id}-food`}
          placeholder={`Search foods for "${line.name}"`}
          onPick={pickFood}
        />
        {update.isPending ? (
          <p className="text-xs text-muted-foreground" role="status">
            Saving…
          </p>
        ) : null}
        <ErrorAlert error={update.error} />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="self-start"
          onClick={() => (line.food ? setPicking(false) : onDone())}
        >
          Cancel
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-3 pt-2" aria-label={`Edit ${label}`}>
      <div className="flex items-center justify-between gap-2 rounded-lg bg-muted px-3 py-2">
        <span className="min-w-0 text-sm">{displayName(line.food.description, line.food.brand)}</span>
        <Button type="button" variant="outline" size="sm" onClick={() => setPicking(true)}>
          Change food
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <LabeledInput
          id={`line-${line.id}-quantity`}
          label="Quantity"
          type="number"
          inputMode="decimal"
          step="any"
          min="0"
          required
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`line-${line.id}-unit`}>Unit</Label>
          <NativeSelect
            id={`line-${line.id}-unit`}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          >
            {unitOptions.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <LabeledInput
        id={`line-${line.id}-expires`}
        label="Use by"
        type="date"
        value={expires}
        onChange={(e) => setExpires(e.target.value)}
      />
      <div className="flex items-center gap-3">
        <Switch id={`line-${line.id}-approx`} checked={approx} onCheckedChange={setApprox} />
        <Label htmlFor={`line-${line.id}-approx`} className="font-normal">
          Rough amount
        </Label>
      </div>
      <ErrorAlert error={update.error} />
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={update.isPending}>
          Save
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

// --- one line ----------------------------------------------------------------------------------

function LineRow({ line, receiptId }: { line: ReceiptLine; receiptId: number }) {
  const [editing, setEditing] = useState(false);
  const update = useUpdateReceiptLine(receiptId);
  const rejected = line.status === "rejected";
  const label = lineLabel(line);
  const titleId = `line-${line.id}-title`;
  const amount = lineAmount(line);

  function toggleReject() {
    update.mutate(
      { lineId: line.id, patch: { status: rejected ? "suggested" : "rejected" } },
      {
        onError: (error) =>
          toast.error(error instanceof ApiError ? error.message : `Couldn't update ${label}.`),
      },
    );
  }

  return (
    <li aria-labelledby={titleId} className={cn("flex flex-col gap-1 px-3 py-3")}>
      <div className="flex items-start gap-2">
        <div className={cn("flex min-w-0 flex-1 flex-col gap-0.5", rejected && "opacity-50")}>
          {line.food ? (
            <span id={titleId} className={cn("text-sm font-medium", rejected && "line-through")}>
              {line.food.description}
            </span>
          ) : (
            <span
              id={titleId}
              className="flex items-center gap-1 text-sm font-medium text-destructive"
            >
              <CircleAlertIcon aria-hidden className="size-4 shrink-0" />
              <span>
                No match — pick a food <span className="sr-only">for {line.name}</span>
              </span>
            </span>
          )}
          <span className="truncate font-mono text-xs text-muted-foreground">{line.raw_text}</span>
          {line.food ? (
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              {amount ? <span>{amount}</span> : null}
              {line.approx ? <Badge variant="secondary">approx</Badge> : null}
              <span>
                {line.expires_on ? `use by ${shortDate(line.expires_on)}` : "no use-by date"}
              </span>
            </span>
          ) : null}
          {rejected ? <span className="text-xs">Won&apos;t be added</span> : null}
        </div>
        <div className="flex shrink-0 gap-1">
          {!rejected ? (
            <Button
              variant="ghost"
              size="icon"
              aria-label={line.food ? `Edit ${label}` : `Pick a food for ${line.name}`}
              aria-expanded={editing}
              onClick={() => setEditing((e) => !e)}
            >
              <PencilIcon />
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="icon"
            aria-label={rejected ? `Restore ${label}` : `Reject ${label}`}
            disabled={update.isPending}
            onClick={toggleReject}
          >
            {rejected ? <Undo2Icon /> : <XIcon />}
          </Button>
        </div>
      </div>
      {editing && !rejected ? (
        <LineEditor
          // Picking a food re-estimates amount and use-by on the server: start from those.
          key={[line.food?.id, line.quantity, line.unit, line.expires_on, line.approx].join("|")}
          line={line}
          receiptId={receiptId}
          onDone={() => setEditing(false)}
        />
      ) : null}
    </li>
  );
}

// --- the screens -------------------------------------------------------------------------------

function DeleteButton({ id, label = "Delete receipt" }: { id: number; label?: string }) {
  const router = useRouter();
  const remove = useDeleteReceipt();
  return (
    <Button
      variant="ghost"
      disabled={remove.isPending}
      onClick={() =>
        remove.mutate(id, {
          onSuccess: () => {
            toast.success("Receipt deleted");
            router.push("/pantry/receipts");
          },
          onError: () => toast.error("Couldn't delete the receipt. Try again."),
        })
      }
    >
      <Trash2Icon aria-hidden />
      {label}
    </Button>
  );
}

function Review({ receipt }: { receipt: Receipt }) {
  const router = useRouter();
  const confirm = useConfirmReceipt(receipt.id);
  const adding = receipt.lines.filter(willAdd).length;
  const unmatched = receipt.lines.filter((l) => l.food === null && l.status !== "rejected").length;
  const rejected = receipt.lines.filter((l) => l.status === "rejected").length;

  async function add() {
    // Not mutate(..., { onSuccess }): the confirmed receipt replaces this view before a
    // per-call callback would run, and an unmounted observer never gets it.
    let created;
    try {
      ({ created } = await confirm.mutateAsync());
    } catch {
      return; // the error is shown from confirm.error
    }
    toast.success(`Added ${plural(created.length, "item")} to your pantry`);
    router.push("/pantry");
  }

  if (!receipt.lines.length) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm">
          No food lines found on this receipt. Try a clearer photo, or paste the text instead.
        </p>
        <div className="flex gap-2">
          <Link href="/pantry/receipts" className={buttonVariants()}>
            Try again
          </Link>
          <DeleteButton id={receipt.id} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Check what was read. Fix or reject anything wrong, then add the rest to your pantry.
      </p>
      <ul aria-label="Receipt lines" className="flex flex-col divide-y rounded-lg border">
        {receipt.lines.map((line) => (
          <LineRow key={line.id} line={line} receiptId={receipt.id} />
        ))}
      </ul>
      <div
        className="flex flex-col gap-2 rounded-xl border bg-muted/40 p-3"
        aria-live="polite"
      >
        <p className="text-sm font-medium">{plural(adding, "item")} will be added</p>
        {unmatched || rejected ? (
          <p className="text-xs text-muted-foreground">
            {[
              unmatched ? `${plural(unmatched, "line")} without a food will be skipped` : null,
              rejected ? `${rejected} rejected` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        ) : null}
        <ErrorAlert error={confirm.error} />
        <Button onClick={add} disabled={adding === 0 || confirm.isPending}>
          {confirm.isPending ? "Adding…" : `Add ${plural(adding, "item")} to pantry`}
        </Button>
      </div>
      <DeleteButton id={receipt.id} />
    </div>
  );
}

function Reading({
  receipt,
  onRetry,
  gaveUp,
}: {
  receipt: Receipt;
  onRetry: () => void;
  gaveUp: boolean;
}) {
  if (gaveUp) {
    return (
      <div className="flex flex-col gap-3">
        <Alert>
          <CircleAlertIcon />
          <AlertTitle>This is taking longer than it should</AlertTitle>
          <AlertDescription>
            The receipt is still waiting to be read. Check again in a minute, or delete it and try
            once more.
          </AlertDescription>
        </Alert>
        <div className="flex gap-2">
          <Button onClick={onRetry}>Check again</Button>
          <DeleteButton id={receipt.id} />
        </div>
      </div>
    );
  }
  return (
    <div role="status" className="flex flex-col items-center gap-3 py-12 text-center">
      <LoaderCircleIcon aria-hidden className="size-8 animate-spin text-muted-foreground" />
      <p className="text-sm font-medium">Reading your receipt…</p>
      <p className="text-xs text-muted-foreground">
        {receipt.source === "image" ? "Photos take a few seconds." : "This takes a moment."}
      </p>
    </div>
  );
}

function Failed({ receipt }: { receipt: Receipt }) {
  return (
    <div className="flex flex-col gap-3">
      <Alert variant="destructive" role="alert">
        <CircleAlertIcon />
        <AlertTitle>Couldn&apos;t read this receipt</AlertTitle>
        <AlertDescription>{receipt.error ?? "Something went wrong reading it."}</AlertDescription>
      </Alert>
      <div className="flex gap-2">
        <Link
          href={`/pantry/receipts${receipt.source === "text" ? "?tab=text" : ""}`}
          className={buttonVariants()}
        >
          Try again
        </Link>
        <DeleteButton id={receipt.id} />
      </div>
    </div>
  );
}

function Confirmed({ receipt }: { receipt: Receipt }) {
  const added = receipt.lines.filter((l) => l.pantry_item_id !== null);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm">
        {plural(added.length, "item")} from this receipt {added.length === 1 ? "is" : "are"} in your
        pantry.
      </p>
      <ul className="flex flex-col divide-y rounded-lg border text-sm">
        {added.map((l) => (
          <li key={l.id} className="px-3 py-2">
            {l.food?.description ?? l.name}
          </li>
        ))}
      </ul>
      <Link href="/pantry" className={buttonVariants({ className: "self-start" })}>
        Go to pantry
      </Link>
    </div>
  );
}

/** One receipt: wait while it's read, then review its lines and add them to the pantry. */
export function ReceiptReview({
  id,
  giveUpAfterMs = GIVE_UP_MS,
}: {
  id: number;
  giveUpAfterMs?: number;
}) {
  const [gaveUp, setGaveUp] = useState(false);
  const { data: receipt, error, isPending, refetch } = useReceipt(id, { poll: !gaveUp });
  const reading = isReading(receipt?.status);

  useEffect(() => {
    if (!reading || gaveUp) return;
    const timer = setTimeout(() => setGaveUp(true), giveUpAfterMs);
    return () => clearTimeout(timer);
  }, [reading, gaveUp, giveUpAfterMs]);

  let body: React.ReactNode;
  if (isPending) {
    body = <Skeleton className="h-40" />;
  } else if (!receipt) {
    body =
      error instanceof ApiError && error.status === 404 ? (
        <p className="text-sm">This receipt doesn&apos;t exist any more.</p>
      ) : (
        <ErrorAlert error={error} />
      );
  } else if (reading) {
    body = (
      <Reading
        receipt={receipt}
        gaveUp={gaveUp}
        onRetry={() => {
          setGaveUp(false);
          void refetch();
        }}
      />
    );
  } else if (receipt.status === "failed") {
    body = <Failed receipt={receipt} />;
  } else if (receipt.status === "confirmed") {
    body = <Confirmed receipt={receipt} />;
  } else {
    body = <Review receipt={receipt} />;
  }

  return (
    <div className="flex flex-col gap-4">
      <BackLink href="/pantry/receipts">Receipts</BackLink>
      <div className="flex flex-col gap-0.5">
        <h1 className="text-2xl font-semibold tracking-tight">Review receipt</h1>
        {receipt ? (
          <p className="text-xs text-muted-foreground">
            {receipt.source === "image" ? "Photo" : "Pasted text"} · bought{" "}
            {shortDate(receipt.purchased_on)}
          </p>
        ) : null}
      </div>
      {body}
    </div>
  );
}
