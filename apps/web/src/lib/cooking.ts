/** Cook mode helpers: a method split into steps, timers read from a step, amounts scaled. */

import { formatGrams } from "./format";

export type StepTimer = { label: string; seconds: number };

const UNITS: Record<string, number> = {
  second: 1,
  sec: 1,
  minute: 60,
  min: 60,
  hour: 3600,
  hr: 3600,
};

// "20 minutes", "1-2 hours", "30 to 40 mins", "1½ hours", "45 secs"
const TIME =
  /(\d+(?:[.,]\d+)?½?|½)(?:\s*(?:-|–|to)\s*(\d+(?:[.,]\d+)?))?\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b/gi;

function num(text: string): number {
  const half = text.endsWith("½") ? 0.5 : 0;
  const whole = text.replace("½", "");
  return (whole ? Number(whole.replace(",", ".")) : 0) + half;
}

/**
 * Timers a step mentions, in order: "simmer for 20-25 minutes" -> 25 min (the longer end, so
 * nothing comes out underdone; the cook can stop early). At most 3 per step, 1 s to 12 h.
 */
export function stepTimers(step: string): StepTimer[] {
  const out: StepTimer[] = [];
  for (const m of step.matchAll(TIME)) {
    const unit = m[3]!.toLowerCase().replace(/s$/, "");
    const each = UNITS[unit];
    if (!each) continue;
    const amount = num(m[2] ?? m[1]!);
    const seconds = Math.round(amount * each);
    if (seconds < 1 || seconds > 12 * 3600) continue;
    out.push({ label: m[0].trim(), seconds });
    if (out.length === 3) break;
  }
  return out;
}

/** 95 -> "1:35", 3725 -> "1:02:05" */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** The factor that turns a recipe's amounts into `servings` (the recipe's own when unknown). */
export function scaleFactor(servings: number, recipeServings: number | null | undefined): number {
  if (!recipeServings || recipeServings <= 0 || servings <= 0) return 1;
  return servings / recipeServings;
}

/** An ingredient's amount at `factor` times the recipe: as written at 1 (or without grams),
 * else its grams scaled ("2 tbsp" doesn't scale as text). */
export function scaledAmount(
  ing: { measure: string; grams: number | null },
  factor: number,
): string {
  if (factor === 1 || ing.grams == null) return ing.measure || "";
  return formatGrams(ing.grams * factor);
}

/** Servings to cook for a planned meal: the user's own times everyone they cook for, in
 * halves, at most 20 (what ?servings= takes). */
export function cookServings(servings: number, household = 1): number {
  return Math.min(20, Math.round(servings * household * 2) / 2);
}

/** Servings from a ?servings= value: halves from 0.5 to 20, else null. */
export function parseServings(value: string | null): number | null {
  if (!value) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  const halves = Math.round(n * 2) / 2;
  return halves >= 0.5 && halves <= 20 ? halves : null;
}

// "STEP 1", "Step 2:", "3. " or "4) " at the start of a line: the numbering is ours to show.
// A number needs a space after its point, so "1.5 kg" stays.
const NUMBERING = /^(?:step\s*\d+\s*[.):-]?\s*|\d{1,2}[.)]\s+)/i;

/**
 * A recipe's method as steps: one per line, without the "STEP 1" headings and "1." numbers
 * some sources write (a heading on its own line is dropped, a number before text is removed).
 * A line that carries on a sentence (lower case, after a line with no closing punctuation)
 * joins the one before it, so text wrapped mid-sentence stays one step.
 */
export function steps(instructions: string): string[] {
  const out: string[] = [];
  for (const line of instructions.split(/\r?\n+/)) {
    const s = line.trim().replace(NUMBERING, "").trim();
    if (!s) continue;
    const last = out.at(-1);
    if (last !== undefined && /^[a-z]/.test(s) && !/[.!?:;]$/.test(last)) {
      out[out.length - 1] = `${last} ${s}`;
    } else {
      out.push(s);
    }
  }
  return out;
}
