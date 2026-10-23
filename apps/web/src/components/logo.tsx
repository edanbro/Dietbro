import { APP_NAME } from "@/lib/brand";

/** The mark's strokes on a 24-unit grid (also drawn into public/icon.svg). */
export const MARK_PATHS = [
  // The bowl.
  "M3.5 12.5h17a8.5 8.5 0 0 1-17 0z",
  // The sprout growing out of it.
  "M12 12.5V8",
  "M12 9.2C12 6.6 10.2 5 7.4 5c0 2.6 1.8 4.2 4.6 4.2z",
  "M12 8c0-2.6 1.8-4.2 4.6-4.2 0 2.6-1.8 4.2-4.6 4.2z",
];

/** Mealwright's mark: a bowl with a sprout. Line art in the current colour. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      {MARK_PATHS.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/** The mark on its green tile, with the name in the heading face. */
export function Logo({ size = "md" }: { size?: "md" | "lg" }) {
  const tile = size === "lg" ? "size-10 rounded-xl" : "size-8 rounded-lg";
  const mark = size === "lg" ? "size-6" : "size-5";
  const text = size === "lg" ? "text-2xl" : "text-lg";
  return (
    <span className="flex items-center gap-2">
      <span className={`grid place-items-center bg-primary text-primary-foreground ${tile}`}>
        <LogoMark className={mark} />
      </span>
      <span className={`font-heading font-semibold tracking-tight ${text}`}>{APP_NAME}</span>
    </span>
  );
}
