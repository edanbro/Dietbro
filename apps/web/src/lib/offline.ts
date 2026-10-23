/**
 * Offline support kept in the app, per signed-in user (never in the service worker's shared
 * cache): the last copy of the current plan and its shopping list, and shopping ticks made
 * while offline, sent when the connection is back. Storage can be unavailable (private mode,
 * blocked site data): then nothing is kept and everything works online as before.
 */

const PREFIX = "mw:";

function read<T>(key: string): T | undefined {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw ? (JSON.parse(raw) as T) : undefined;
  } catch {
    return undefined;
  }
}

function write(key: string, value: unknown): void {
  try {
    if (value === undefined) localStorage.removeItem(PREFIX + key);
    else localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // Full or blocked: offline copies are a convenience.
  }
}

/** The last copy of something the user saw (`what`: "plan", "shopping:7"...). */
export function loadSnapshot<T>(user: string | null | undefined, what: string): T | undefined {
  return user ? read<T>(`${user}:${what}`) : undefined;
}

export function saveSnapshot(user: string | null | undefined, what: string, value: unknown) {
  if (user) write(`${user}:${what}`, value);
}

export type PendingTick = { planId: number; foodId: number; checked: boolean };

/** Ticks waiting to be sent, oldest first; a later tick of the same line replaces it. */
export function pendingTicks(user: string | null | undefined): PendingTick[] {
  return (user && read<PendingTick[]>(`${user}:ticks`)) || [];
}

export function queueTick(user: string | null | undefined, tick: PendingTick): void {
  if (!user) return;
  const rest = pendingTicks(user).filter(
    (t) => !(t.planId === tick.planId && t.foodId === tick.foodId),
  );
  write(`${user}:ticks`, [...rest, tick]);
}

export function dropTicks(user: string | null | undefined, sent: PendingTick[]): void {
  if (!user) return;
  const left = pendingTicks(user).filter(
    (t) =>
      !sent.some((s) => s.planId === t.planId && s.foodId === t.foodId && s.checked === t.checked),
  );
  write(`${user}:ticks`, left.length ? left : undefined);
}

/** Whether a failed request never reached the server (offline, DNS, dropped connection). */
export function isNetworkError(error: unknown): boolean {
  return (
    (typeof navigator !== "undefined" && navigator.onLine === false) ||
    error instanceof TypeError
  );
}

/** On sign-out: forget every offline copy on this device (and the service worker's pages). */
export function clearOfflineData(): void {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(PREFIX)) localStorage.removeItem(key);
    }
  } catch {
    // Nothing stored.
  }
  if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
    navigator.serviceWorker.controller?.postMessage("clear-pages");
  }
}
