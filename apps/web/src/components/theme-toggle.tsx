"use client";

import { cn } from "cn";
import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";

import { applyTheme, readTheme, type Theme, THEME_KEY } from "@/lib/theme";

const OPTIONS: { value: Theme; label: string; icon: typeof SunIcon }[] = [
  { value: "system", label: "System", icon: MonitorIcon },
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
];

// Every toggle on the page (rail, profile) shows the same choice; other tabs follow via storage.
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key !== null && e.key !== THEME_KEY) return;
    applyTheme(readTheme()); // chosen in another tab: this one follows
    onChange();
  };
  listeners.add(onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** The theme in use, kept in step with the device's setting while on System. */
export function useTheme(): [Theme, (theme: Theme) => void] {
  // The server can't know it: "system" there, the stored choice after hydration.
  const theme = useSyncExternalStore(subscribe, readTheme, () => "system" as const);
  useEffect(() => {
    if (theme !== "system" || typeof matchMedia !== "function") return;
    const media = matchMedia("(prefers-color-scheme: dark)");
    const follow = () => applyTheme("system");
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, [theme]);
  return [
    theme,
    (next) => {
      applyTheme(next);
      listeners.forEach((l) => l());
    },
  ];
}

/** System / Light / Dark as a segmented control. `compact`: icons only (with names). */
export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useTheme();
  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="inline-grid grid-cols-3 gap-1 rounded-lg bg-muted p-1"
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={theme === value}
          aria-label={compact ? label : undefined}
          title={compact ? label : undefined}
          onClick={() => setTheme(value)}
          className={cn(
            "flex h-8 items-center justify-center gap-1.5 rounded-md px-2.5 text-sm transition-colors",
            theme === value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icon aria-hidden className="size-4" />
          {compact ? null : label}
        </button>
      ))}
    </div>
  );
}
