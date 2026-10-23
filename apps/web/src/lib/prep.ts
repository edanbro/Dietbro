/**
 * Meal prep: several recipes cooked together, their steps merged into one timeline for one cook.
 *
 * Each step is estimated from its words (cooking.ts reads its timers):
 * - Passive: a waiting verb (simmer, bake, roast, rest...) with a timer. The cook spends a minute
 *   starting it, then the recipe waits out the timer while the cook does something else.
 * - Active: everything else. A timer counts as hands-on time ("fry for 5 minutes"); without one,
 *   the step's length gives 1-8 minutes.
 *
 * Scheduling: steps stay in order within a recipe. Whenever the cook is free, they take the next
 * step of the recipe with the most time left (the critical path), among those not waiting; if all
 * are waiting, the cook waits for the first to be ready. So long simmers start early and fill with
 * other recipes' chopping. Not optimal in every case, and doesn't need to be: it's a guide.
 */

import { type StepTimer, stepTimers } from "./cooking";

export type PrepRecipe = { id: number; name: string; steps: string[] };

export type Estimate = { active: number; passive: number; timer: StepTimer | null };

export type PrepEvent = {
  recipeId: number;
  recipe: string;
  index: number; // the step's place in its recipe
  step: string;
  start: number; // seconds from the start
  active: number; // hands-on seconds
  passive: number; // waiting seconds after that
  timer: StepTimer | null;
};

const PASSIVE =
  /\b(simmer|bake|roast|boil|rest|marinate|chill|leave|stew|braise|steam|soak|prove|refrigerate|slow[- ]cook|set aside)/i;
const SETUP = 60; // starting a passive step
const MIN_ACTIVE = 60;
const MAX_ACTIVE = 8 * 60;
const WORDS_PER_MINUTE = 12;

export function estimate(step: string): Estimate {
  const timers = stepTimers(step);
  const timer = timers.length ? timers.reduce((a, b) => (b.seconds > a.seconds ? b : a)) : null;
  if (timer && PASSIVE.test(step)) return { active: SETUP, passive: timer.seconds, timer };
  if (timer) return { active: timer.seconds, passive: 0, timer };
  const words = step.trim().split(/\s+/).filter(Boolean).length;
  const active = Math.min(
    MAX_ACTIVE,
    Math.max(MIN_ACTIVE, Math.round(words / WORDS_PER_MINUTE) * 60),
  );
  return { active, passive: 0, timer: null };
}

/** The merged timeline, in the order the cook does things. */
export function schedule(recipes: PrepRecipe[]): PrepEvent[] {
  const steps = recipes.map((r) => r.steps.map(estimate));
  const next = recipes.map(() => 0);
  const ready = recipes.map(() => 0); // when each recipe's previous step is done
  const left = (r: number) =>
    steps[r]!.slice(next[r]).reduce((sum, e) => sum + e.active + e.passive, 0);
  const events: PrepEvent[] = [];
  let free = 0; // when the cook is free
  for (;;) {
    const open = recipes.map((_, r) => r).filter((r) => next[r]! < steps[r]!.length);
    if (!open.length) return events;
    let now = free;
    let waiting = open.filter((r) => ready[r]! <= now);
    if (!waiting.length) {
      now = Math.min(...open.map((r) => ready[r]!));
      waiting = open.filter((r) => ready[r]! <= now);
    }
    const r = waiting.reduce((best, c) => (left(c) > left(best) ? c : best));
    const i = next[r]!;
    const e = steps[r]![i]!;
    events.push({
      recipeId: recipes[r]!.id,
      recipe: recipes[r]!.name,
      index: i,
      step: recipes[r]!.steps[i]!,
      start: now,
      active: e.active,
      passive: e.passive,
      timer: e.timer,
    });
    free = now + e.active;
    ready[r] = now + e.active + e.passive;
    next[r] = i + 1;
  }
}

/** When everything is done, in seconds from the start. */
export function totalTime(events: PrepEvent[]): number {
  return events.reduce((end, e) => Math.max(end, e.start + e.active + e.passive), 0);
}

/** "r=12x2,34x4": recipe ids with servings (halves from 0.5 to 20), at most `max` recipes. */
export function parsePrep(value: string | null, max = 4): { id: number; servings: number }[] {
  if (!value) return [];
  const out: { id: number; servings: number }[] = [];
  for (const part of value.split(",")) {
    const m = /^([1-9]\d{0,8})x(\d+(?:\.5)?)$/.exec(part.trim());
    if (!m) continue;
    const servings = Number(m[2]);
    const id = Number(m[1]);
    if (servings < 0.5 || servings > 20 || out.some((o) => o.id === id)) continue;
    out.push({ id, servings });
    if (out.length === max) break;
  }
  return out;
}
