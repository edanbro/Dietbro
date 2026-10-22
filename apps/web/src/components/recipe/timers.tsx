"use client";

import { cn } from "cn";
import { PauseIcon, PlayIcon, RotateCcwIcon, TimerIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { clock, type StepTimer } from "@/lib/cooking";

/** One countdown: `left` seconds while paused, or running until `endsAt` (ms). */
type Countdown = { label: string; seconds: number; left: number; endsAt: number | null };

export type Timers = {
  /** The countdown for `id`, or a fresh one for `timer` if it was never started. */
  state(id: string, timer: StepTimer): Countdown;
  toggle(id: string, timer: StepTimer): void;
  reset(id: string): void;
  /** Started and not reset: running, paused part-way, or just finished. */
  active: [string, Countdown][];
};

function remaining(c: Countdown, now: number): number {
  return c.endsAt === null ? c.left : Math.max(0, Math.round((c.endsAt - now) / 1000));
}

/**
 * Every timer on the page in one place, so they keep counting while you scroll and can be shown
 * together (the bar at the bottom). Finishing buzzes the phone and says so.
 */
export function useTimers(): Timers {
  const [timers, setTimers] = useState<Record<string, Countdown>>({});
  const [now, setNow] = useState(() => Date.now());
  const running = Object.values(timers).some((c) => c.endsAt !== null);
  const latest = useRef(timers);
  useEffect(() => {
    latest.current = timers;
  });

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => {
      const t = Date.now();
      setNow(t);
      const finished = Object.entries(latest.current).filter(
        ([, c]) => c.endsAt !== null && remaining(c, t) === 0,
      );
      if (!finished.length) return;
      setTimers((all) => {
        const next = { ...all };
        for (const [key, c] of finished) next[key] = { ...c, left: 0, endsAt: null };
        return next;
      });
      navigator.vibrate?.([300, 150, 300]);
      for (const [, c] of finished) toast.success(`Timer done: ${c.label}`);
    }, 250);
    return () => clearInterval(id);
  }, [running]);

  const state = useCallback(
    (id: string, timer: StepTimer): Countdown => {
      const c = timers[id];
      if (!c)
        return { label: timer.label, seconds: timer.seconds, left: timer.seconds, endsAt: null };
      return { ...c, left: remaining(c, now) };
    },
    [timers, now],
  );

  const toggle = useCallback((id: string, timer: StepTimer) => {
    const t = Date.now();
    setNow(t);
    setTimers((all) => {
      const c = all[id] ?? {
        label: timer.label,
        seconds: timer.seconds,
        left: timer.seconds,
        endsAt: null,
      };
      if (c.endsAt !== null) return { ...all, [id]: { ...c, left: remaining(c, t), endsAt: null } };
      if (c.left === 0) return all;
      return { ...all, [id]: { ...c, endsAt: t + c.left * 1000 } };
    });
  }, []);

  const reset = useCallback((id: string) => {
    setTimers((all) => {
      const next = { ...all };
      delete next[id];
      return next;
    });
  }, []);

  const active = useMemo(
    () =>
      Object.entries(timers).map(([id, c]): [string, Countdown] => [
        id,
        { ...c, left: remaining(c, now) },
      ]),
    [timers, now],
  );

  return { state, toggle, reset, active };
}

/** A timer read from a step ("20 minutes"): start, pause, reset. */
export function TimerChip({ id, timer, timers }: { id: string; timer: StepTimer; timers: Timers }) {
  const c = timers.state(id, timer);
  const done = c.left === 0;
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 rounded-full border py-0.5 pr-0.5 pl-2.5 text-sm tabular-nums",
        c.endsAt !== null && "border-primary bg-primary/5",
        done && "border-emerald-500 text-emerald-700 dark:text-emerald-400",
      )}
    >
      <TimerIcon aria-hidden className="size-3.5" />
      <span aria-live={c.endsAt !== null ? "off" : "polite"} aria-label={`${timer.label} timer`}>
        {clock(c.left)}
      </span>
      {done ? null : (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={c.endsAt !== null ? `Pause ${timer.label}` : `Start ${timer.label}`}
          onClick={() => timers.toggle(id, timer)}
        >
          {c.endsAt !== null ? <PauseIcon /> : <PlayIcon />}
        </Button>
      )}
      {c.left !== c.seconds ? (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Reset ${timer.label}`}
          onClick={() => timers.reset(id)}
        >
          <RotateCcwIcon />
        </Button>
      ) : null}
    </div>
  );
}

/**
 * The timers in use, pinned to the bottom of the screen so they stay in sight while you scroll.
 * `name` labels each one (in meal prep: which recipe it belongs to).
 */
export function RunningTimers({
  timers,
  name,
}: {
  timers: Timers;
  name?: (id: string) => string | undefined;
}) {
  if (!timers.active.length) return null;
  return (
    <section
      aria-label="Timers"
      className="sticky bottom-3 z-10 flex flex-wrap gap-2 rounded-2xl border bg-background/95 p-2 shadow-lg backdrop-blur"
    >
      {timers.active.map(([id, c]) => {
        const done = c.left === 0;
        const owner = name?.(id);
        return (
          <div
            key={id}
            className={cn(
              "flex items-center gap-1 rounded-xl bg-muted py-1 pr-1 pl-3 text-sm",
              done && "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
            )}
          >
            <span className="flex flex-col leading-tight">
              <span className="text-base font-semibold tabular-nums">
                {done ? "Done" : clock(c.left)}
              </span>
              <span className="max-w-40 truncate text-xs text-muted-foreground">
                {owner ? `${owner}: ` : ""}
                {c.label}
              </span>
            </span>
            {done ? null : (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={c.endsAt !== null ? `Pause ${c.label}` : `Start ${c.label}`}
                onClick={() => timers.toggle(id, { label: c.label, seconds: c.seconds })}
              >
                {c.endsAt !== null ? <PauseIcon /> : <PlayIcon />}
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Clear ${c.label}`}
              onClick={() => timers.reset(id)}
            >
              <XIcon />
            </Button>
          </div>
        );
      })}
    </section>
  );
}
