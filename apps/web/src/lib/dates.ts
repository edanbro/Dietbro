/**
 * Calendar dates as ISO strings ("2026-10-09") in the user's *local* time zone.
 *
 * Plans are made for the user's local week, so "today" must come from the local calendar,
 * never from `toISOString()` (UTC), which is a day off for part of the day east or west of UTC.
 */

import { dateFormat } from "@/lib/locale";

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

const WEEKDAY: Intl.DateTimeFormatOptions = { weekday: "short" };
const DAY_MONTH: Intl.DateTimeFormatOptions = { weekday: "short", day: "numeric", month: "short" };
const LONG: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" };
const MONTH: Intl.DateTimeFormatOptions = { month: "long" };

/** "Fri" */
export function weekday(iso: string): string {
  return dateFormat(WEEKDAY).format(parseISODate(iso));
}

/** "9" */
export function dayOfMonth(iso: string): number {
  return parseISODate(iso).getDate();
}

/** "October" */
export function monthName(iso: string): string {
  return dateFormat(MONTH).format(parseISODate(iso));
}

/** "Fri 9 Oct" */
export function shortDate(iso: string): string {
  return dateFormat(DAY_MONTH).format(parseISODate(iso));
}

/** "Friday 9 October" */
export function longDate(iso: string): string {
  return dateFormat(LONG).format(parseISODate(iso));
}

/** "Fri 9 Oct – Thu 15 Oct" */
export function dateRange(first: string, last: string): string {
  return first === last ? shortDate(first) : `${shortDate(first)} – ${shortDate(last)}`;
}

/** The local wall-clock time of `d` as HH:MM:SS (what the chat sends as `local_time`). */
export function localTime(d: Date = new Date()): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// 24-hour whatever the OS prefers (Windows can make en-GB print "02:05" for 14:05).
const CLOCK: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };

/**
 * When something comes back, relative to `now` in local time: "14:05" today, "tomorrow at
 * 09:12", otherwise "Sun 1 Nov at 00:00".
 */
export function formatWhen(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  const days = daysBetween(localISODate(now), localISODate(at));
  const clock = dateFormat(CLOCK).format(at);
  if (days === 0) return clock;
  if (days === 1) return `tomorrow at ${clock}`;
  return `${shortDate(localISODate(at))} at ${clock}`;
}
