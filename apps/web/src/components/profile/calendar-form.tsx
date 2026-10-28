"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlusIcon, CopyIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert } from "@/components/form-bits";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PUBLIC_API_URL, unwrap, useApi } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";

type Calendar = components["schemas"]["CalendarOut"];
type Times = components["schemas"]["CalendarTimes"];

const KEY = ["me", "calendar"] as const;
const SLOTS = [
  ["breakfast", "Breakfast"],
  ["lunch", "Lunch"],
  ["dinner", "Dinner"],
  ["snack", "Snack"],
] as const;

/** The feed's full address, and the same as webcal:// (calendar apps open that to subscribe). */
export function feedUrls(path: string, api: string = PUBLIC_API_URL) {
  const https = new URL(path, api).toString();
  const webcal = https.replace(/^https?:/, "webcal:");
  return {
    https,
    webcal,
    google: `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcal)}`,
  };
}

function Times({ times }: { times: Times }) {
  const api = useApi();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Times>(times);
  const save = useMutation({
    mutationFn: async (body: Times) => unwrap(await api.PUT("/me/calendar/times", { body })),
    onSuccess: (data) => {
      qc.setQueryData(KEY, data);
      toast.success("Meal times saved");
    },
  });
  return (
    <form
      className="flex flex-col gap-3"
      aria-label="Meal times on the calendar"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(draft);
      }}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {SLOTS.map(([slot, label]) => (
          <div key={slot} className="flex flex-col gap-1.5">
            <Label htmlFor={`cal-${slot}`}>{label}</Label>
            <Input
              id={`cal-${slot}`}
              type="time"
              required
              value={draft[slot]}
              onChange={(e) => setDraft({ ...draft, [slot]: e.target.value })}
            />
          </div>
        ))}
      </div>
      <ErrorAlert error={save.error} />
      <Button type="submit" variant="outline" className="self-start" disabled={save.isPending}>
        Save times
      </Button>
    </form>
  );
}

/**
 * Your planned meals in your own calendar app: a private address it subscribes to, which
 * follows swaps and replans by itself. Reset makes a new address if the old one got out.
 */
export function CalendarForm() {
  const api = useApi();
  const qc = useQueryClient();
  const calendar = useQuery({
    queryKey: KEY,
    queryFn: async () => unwrap(await api.GET("/me/calendar")),
  });
  const change = useMutation({
    mutationFn: async (action: "reset" | "off"): Promise<Calendar> =>
      action === "reset"
        ? unwrap(await api.POST("/me/calendar"))
        : unwrap(await api.DELETE("/me/calendar")),
    onSuccess: (data) => qc.setQueryData(KEY, data),
  });

  if (calendar.isPending) return null;
  if (calendar.error) {
    return <ErrorAlert error={calendar.error} onRetry={() => void calendar.refetch()} />;
  }
  const data = calendar.data;

  if (!data.enabled || !data.path) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-sm text-muted-foreground">
          See each meal in Google, Apple or Outlook Calendar, next to everything else. It
          updates by itself when your plan changes.
        </p>
        <ErrorAlert error={change.error} />
        <Button disabled={change.isPending} onClick={() => change.mutate("reset")}>
          <CalendarPlusIcon aria-hidden />
          Add to my calendar
        </Button>
      </div>
    );
  }

  const urls = feedUrls(data.path);
  async function copy() {
    try {
      await navigator.clipboard.writeText(urls.https);
      toast.success("Calendar address copied");
    } catch {
      toast.message(urls.https, { description: "Copy this address" });
    }
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        <a href={urls.webcal} className={buttonVariants()}>
          Apple or Outlook
        </a>
        <a
          href={urls.google}
          target="_blank"
          rel="noreferrer"
          className={buttonVariants({ variant: "outline" })}
        >
          Google Calendar
        </a>
        <Button variant="outline" onClick={() => void copy()}>
          <CopyIcon aria-hidden />
          Copy address
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Keep this address private: anyone with it can see your planned meals. Google refreshes
        subscribed calendars every few hours; Apple and Outlook about hourly.
      </p>
      <Times times={data.times} />
      <ErrorAlert error={change.error} />
      <div className="flex flex-wrap gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={change.isPending}
          onClick={() => change.mutate("reset", { onSuccess: () => toast.success("New calendar address ready. The old one no longer works.") })}
        >
          Reset address
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={change.isPending}
          onClick={() => change.mutate("off")}
        >
          Turn off
        </Button>
      </div>
    </div>
  );
}
