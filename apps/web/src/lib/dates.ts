/**
 * Calendar dates as ISO strings ("2026-10-09") in the user's *local* time zone.
 *
 * Plans are made for the user's local week, so "today" must come from the local calendar,
 * never from `toISOString()` (UTC), which is a day off for part of the day east or west of UTC.
 */

const DAY_MS = 86_400_000;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** The local calendar date of `d` as YYYY-MM-DD. */
export function localISODate(d: Date = new Date()): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Local midnight of an ISO date. */
export function parseISODate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Whole calendar days from `from` to `to` (negative when `to` is earlier). */
export function daysBetween(from: string, to: string): number {
  const [fy, fm, fd] = from.split("-").map(Number);
  const [ty, tm, td] = to.split("-").map(Number);
  return Math.round((Date.UTC(ty, tm - 1, td) - Date.UTC(fy, fm - 1, fd)) / DAY_MS);
}

export function addDays(iso: string, days: number): string {
  const d = parseISODate(iso);
  d.setDate(d.getDate() + days);
  return localISODate(d);
}

const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short" });
const DAY_MONTH = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
});
const LONG = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });
const MONTH = new Intl.DateTimeFormat("en-GB", { month: "long" });

/** "Fri" */
export function weekday(iso: string): string {
  return WEEKDAY.format(parseISODate(iso));
}

/** "9" */
export function dayOfMonth(iso: string): number {
  return parseISODate(iso).getDate();
}

/** "October" */
export function monthName(iso: string): string {
  return MONTH.format(parseISODate(iso));
}

/** "Fri 9 Oct" */
export function shortDate(iso: string): string {
  return DAY_MONTH.format(parseISODate(iso));
}

/** "Friday 9 October" */
export function longDate(iso: string): string {
  return LONG.format(parseISODate(iso));
}

/** "Fri 9 Oct – Thu 15 Oct" */
export function dateRange(first: string, last: string): string {
  return first === last ? shortDate(first) : `${shortDate(first)} – ${shortDate(last)}`;
}
