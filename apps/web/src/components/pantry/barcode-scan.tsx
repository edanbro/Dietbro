"use client";

import { ScanBarcodeIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorAlert, LabeledInput } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { type FoodDetail, useBarcodeLookup } from "@/lib/api/hooks";
import { cleanBarcode, createDetector } from "@/lib/barcode";

const SCAN_EVERY_MS = 250;

/**
 * Add a packaged food by its barcode: the rear camera reads it (or type the digits), then the
 * product is looked up and handed to `onFound`. The camera stops as soon as a code is read, the
 * panel closes, or the page unmounts.
 */
export function BarcodeScan({ onFound }: { onFound: (food: FoodDetail) => void }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [cameraProblem, setCameraProblem] = useState<string | null>(null);
  const lookup = useBarcodeLookup();
  const { mutate } = lookup;

  const find = useCallback(
    (code: string) =>
      mutate(code, {
        onSuccess: (food) => {
          setOpen(false);
          setTyped("");
          onFound(food);
        },
      }),
    [mutate, onFound],
  );

  if (!open) {
    return (
      <Button type="button" variant="outline" onClick={() => setOpen(true)}>
        <ScanBarcodeIcon aria-hidden />
        Scan a barcode
      </Button>
    );
  }

  const code = cleanBarcode(typed);
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3" aria-label="Scan a barcode">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Point the camera at the barcode</span>
        <button type="button" aria-label="Close the scanner" onClick={() => setOpen(false)}>
          <XIcon className="size-4" />
        </button>
      </div>
      {cameraProblem ? (
        <p className="text-sm text-muted-foreground">{cameraProblem}</p>
      ) : (
        <Camera paused={lookup.isPending} onCode={find} onProblem={setCameraProblem} />
      )}
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (code) find(code);
        }}
      >
        <div className="flex-1">
          <LabeledInput
            id="barcode"
            label="Or type the digits"
            inputMode="numeric"
            autoComplete="off"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={!code || lookup.isPending}>
          {lookup.isPending ? "Looking up…" : "Look up"}
        </Button>
      </form>
      <ErrorAlert error={lookup.error} />
    </div>
  );
}

function Camera({
  paused,
  onCode,
  onProblem,
}: {
  paused: boolean;
  onCode: (code: string) => void;
  onProblem: (problem: string) => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const last = useRef<string | null>(null);
  const pausedRef = useRef(paused);
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setInterval> | undefined;
    let stopped = false;
    const stop = () => {
      stopped = true;
      clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
    (async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        onProblem("This browser can't use the camera here. Type the barcode instead.");
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
      } catch {
        onProblem("No camera, or permission was refused. Type the barcode instead.");
        return;
      }
      if (stopped || !video.current) return stop();
      video.current.srcObject = stream;
      await video.current.play().catch(() => undefined);
      const detector = await createDetector().catch(() => null);
      if (!detector) {
        onProblem("Couldn't start the barcode reader. Type the barcode instead.");
        return stop();
      }
      timer = setInterval(async () => {
        const el = video.current;
        if (stopped || pausedRef.current || !el || el.readyState < 2) return;
        const found = await detector.detect(el).catch(() => []);
        const code = found.map((b) => cleanBarcode(b.rawValue)).find((c) => c !== null);
        if (code && code !== last.current) {
          last.current = code;
          onCode(code);
        }
      }, SCAN_EVERY_MS);
    })();
    return stop;
  }, [onCode, onProblem]);

  return (
    <video
      ref={video}
      className="aspect-video w-full rounded-md bg-black object-cover"
      muted
      playsInline
      aria-label="Camera preview"
    />
  );
}
