/**
 * A tiny stand-in for `next/navigation` in component tests:
 * `vi.mock("next/navigation", () => import("@/test/navigation"))`.
 * The URL is a module-level store, so `router.replace` re-renders readers of `useSearchParams`.
 */
import { useMemo, useSyncExternalStore } from "react";

let url = new URL("http://localhost/");
const listeners = new Set<() => void>();

export const calls = { replace: [] as string[], push: [] as string[], back: 0 };

export function setUrl(href: string) {
  url = new URL(href, "http://localhost");
  for (const listener of listeners) listener();
}

export function resetNavigation(href = "/") {
  calls.replace = [];
  calls.push = [];
  calls.back = 0;
  setUrl(href);
}

export function currentUrl(): string {
  return url.pathname + url.search;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useSearchParams() {
  const search = useSyncExternalStore(subscribe, () => url.search);
  return useMemo(() => new URLSearchParams(search), [search]);
}

export function usePathname() {
  return useSyncExternalStore(subscribe, () => url.pathname);
}

const router = {
  replace(href: string) {
    calls.replace.push(href);
    setUrl(href);
  },
  push(href: string) {
    calls.push.push(href);
    setUrl(href);
  },
  back() {
    calls.back += 1;
  },
  forward() {},
  refresh() {},
  prefetch() {},
};

export function useRouter() {
  return router;
}
