"use client";

import { CameraIcon, ChevronRightIcon, ImageIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ErrorAlert, LabeledInput } from "@/components/form-bits";
import { BackLink, ReceiptStatusBadge } from "@/components/pantry/receipt-bits";
import { Button, buttonVariants } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  type Receipt,
  useReceipts,
  useSubmitReceiptText,
  useMe,
  useUploadReceiptImage,
} from "@/lib/api/hooks";
import { localISODate, shortDate } from "@/lib/dates";
import { currencySymbol } from "@/lib/region";

export const MAX_PHOTO_BYTES = 8_000_000;
const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"];
const HEIC_ADVICE =
  "HEIC photos aren't supported yet. On iPhone, set Settings › Camera › Formats to " +
  "'Most Compatible' (JPEG), or take a screenshot of the photo and upload that.";

/** Why this photo can't be sent (checked again by the server), or null when it can. */
export function photoProblem(file: Pick<File, "name" | "size" | "type">): string | null {
  const type = file.type.toLowerCase();
  if (type === "image/heic" || type === "image/heif" || /\.hei[cf]$/i.test(file.name)) {
    return HEIC_ADVICE;
  }
  // Some browsers leave the type empty; the extension will do (the server sniffs the bytes).
  const known = PHOTO_TYPES.includes(type) || (!type && /\.(jpe?g|png|webp)$/i.test(file.name));
  if (!known) return "Choose a JPEG, PNG or WebP photo of the receipt.";
  if (file.size > MAX_PHOTO_BYTES) {
    return `That photo is ${(file.size / 1_000_000).toFixed(1)} MB; the limit is 8 MB.`;
  }
  return null;
}

function PhotoForm({ purchasedOn, onQueued }: Form) {
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const upload = useUploadReceiptImage();

  function choose(e: React.ChangeEvent<HTMLInputElement>) {
    const chosen = e.target.files?.[0] ?? null;
    e.target.value = ""; // choosing the same file again still fires change
    if (!chosen) return;
    upload.reset();
    const why = photoProblem(chosen);
    setProblem(why);
    setFile(why ? null : chosen);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    upload.mutate({ file, purchased_on: purchasedOn || undefined }, { onSuccess: onQueued });
  }

  const pick = buttonVariants({ variant: "outline", className: "h-12 flex-1" });
  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-label="Receipt photo">
      <div className="flex gap-2">
        <label className={pick}>
          <CameraIcon aria-hidden />
          Take photo
          <input
            type="file"
            accept={PHOTO_TYPES.join(",")}
            capture="environment"
            className="sr-only"
            aria-label="Take a photo of the receipt"
            onChange={choose}
          />
        </label>
        <label className={pick}>
          <ImageIcon aria-hidden />
          Choose photo
          <input
            type="file"
            accept={PHOTO_TYPES.join(",")}
            className="sr-only"
            aria-label="Choose a photo of the receipt"
            onChange={choose}
          />
        </label>
      </div>
      <p className="text-xs text-muted-foreground">
        Flat, in good light, the whole receipt in frame. JPEG, PNG or WebP up to 8 MB (iPhone HEIC
        photos: set the camera to Most Compatible).
      </p>
      {problem ? (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      ) : null}
      {file ? (
        <p className="truncate text-sm">
          {file.name} · {(file.size / 1_000_000).toFixed(1)} MB
        </p>
      ) : null}
      <ErrorAlert error={upload.error} />
      <Button type="submit" disabled={!file || upload.isPending}>
        {upload.isPending ? "Uploading…" : upload.error ? "Try again" : "Read receipt"}
      </Button>
    </form>
  );
}

function TextForm({ purchasedOn, onQueued }: Form) {
  const [text, setText] = useState("");
  const submit = useSubmitReceiptText();
  const { data: me } = useMe();
  const symbol = currencySymbol(me?.region.currency ?? "GBP");

  function send(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    submit.mutate({ text, purchased_on: purchasedOn || undefined }, { onSuccess: onQueued });
  }

  return (
    <form onSubmit={send} className="flex flex-col gap-3" aria-label="Paste receipt text">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="receipt-text">Receipt text</Label>
        <textarea
          id="receipt-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={20_000}
          rows={8}
          placeholder={`Paste an online order or e-receipt, e.g.\nSEMI SKMD MILK 2L   ${symbol}1.45`}
          className="min-h-40 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 font-mono text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        />
      </div>
      <ErrorAlert error={submit.error} />
      <Button type="submit" disabled={!text.trim() || submit.isPending}>
        {submit.isPending ? "Sending…" : submit.error ? "Try again" : "Read receipt"}
      </Button>
    </form>
  );
}

type Form = { purchasedOn: string; onQueued: (receipt: Receipt) => void };

function RecentReceipts() {
  const { data } = useReceipts();
  if (!data?.length) return null;
  return (
    <section aria-labelledby="recent-receipts" className="flex flex-col gap-2">
      <h2 id="recent-receipts" className="text-sm font-semibold">
        Recent receipts
      </h2>
      <ul className="flex flex-col divide-y rounded-lg border">
        {data.slice(0, 5).map((r) => (
          <li key={r.id}>
            <Link
              href={`/pantry/receipts/${r.id}`}
              className="flex items-center gap-3 px-3 py-2.5 hover:bg-muted"
            >
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="text-sm">
                  {r.source === "image" ? "Photo" : "Pasted text"} · {shortDate(r.purchased_on)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {r.status === "failed"
                    ? (r.error ?? "Couldn't read it")
                    : `${r.lines} ${r.lines === 1 ? "line" : "lines"}`}
                </span>
              </span>
              <ReceiptStatusBadge status={r.status} />
              <ChevronRightIcon aria-hidden className="size-4 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Add food from a receipt: photograph it or paste its text, then review what was read. */
export function ReceiptIntake() {
  const router = useRouter();
  const params = useSearchParams();
  const [purchasedOn, setPurchasedOn] = useState(localISODate);
  const onQueued = (receipt: Receipt) => router.push(`/pantry/receipts/${receipt.id}`);

  return (
    <div className="flex flex-col gap-4">
      <BackLink href="/pantry">Pantry</BackLink>
      <h1 className="text-2xl font-semibold tracking-tight">Add from receipt</h1>
      <LabeledInput
        id="purchased-on"
        label="Bought on"
        type="date"
        max={localISODate()}
        value={purchasedOn}
        onChange={(e) => setPurchasedOn(e.target.value)}
        hint="Use-by dates are suggested from this day."
      />
      <Tabs defaultValue={params.get("tab") === "text" ? "text" : "photo"}>
        <TabsList className="w-full">
          <TabsTrigger value="photo">Photo</TabsTrigger>
          <TabsTrigger value="text">Paste text</TabsTrigger>
        </TabsList>
        <TabsContent value="photo" className="pt-2">
          <PhotoForm purchasedOn={purchasedOn} onQueued={onQueued} />
        </TabsContent>
        <TabsContent value="text" className="pt-2">
          <TextForm purchasedOn={purchasedOn} onQueued={onQueued} />
        </TabsContent>
      </Tabs>
      <RecentReceipts />
    </div>
  );
}
