"use client";

import { useEffect, useState } from "react";

/**
 * Keeps the screen on while cooking (Screen Wake Lock), taking the lock again when the tab
 * comes back (browsers drop it when hidden). Unsupported browsers: nothing happens.
 */
export function useWakeLock(): boolean {
  const [held, setHeld] = useState(false);
  useEffect(() => {
    if (!("wakeLock" in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    let cancelled = false;
    const take = async () => {
      try {
        lock = await navigator.wakeLock.request("screen");
        if (cancelled) {
          void lock.release();
          return;
        }
        setHeld(true);
        lock.addEventListener("release", () => setHeld(false));
      } catch {
        setHeld(false); // denied (battery saver) or not visible
      }
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") void take();
    };
    void take();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      void lock?.release();
    };
  }, []);
  return held;
}
