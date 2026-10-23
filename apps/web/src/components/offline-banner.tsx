"use client";

import { WifiOffIcon } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

/** Whether the browser says it's offline (assumed online on the server). */
export function useOffline(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => !navigator.onLine,
    () => false,
  );
}

/** A quiet strip while offline: what's shown is the last copy, and ticks will sync. */
export function OfflineBanner() {
  const offline = useOffline();
  return offline ? (
    <p
      role="status"
      className="flex items-center justify-center gap-2 bg-muted px-4 py-1.5 text-xs text-muted-foreground"
    >
      <WifiOffIcon aria-hidden className="size-3.5" />
      Offline: showing what was last loaded. Changes sync when you&apos;re back.
    </p>
  ) : null;
}

/**
 * Registers the service worker (public/sw.js) in production builds: pages and built assets
 * work offline once visited. Development stays uncached.
 */
export function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" })
      .catch(() => undefined); // offline support is a bonus, never an error
  }, []);
  return null;
}
