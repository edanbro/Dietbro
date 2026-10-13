import { cn } from "cn";

export type NutritionGrade = "A" | "B" | "C" | "D" | "E";

const GRADE_COLOURS: Record<NutritionGrade, string> = {
  A: "bg-emerald-700 text-white",
  B: "bg-lime-600 text-white",
  C: "bg-yellow-400 text-black",
  D: "bg-orange-500 text-black",
  E: "bg-red-600 text-white",
};

/**
 * A–E nutrition grade, worked out with the Nutri-Score method (or a product's own). Deliberately
 * not the official Nutri-Score logo, which is a trademark.
 */
export function GradeBadge({
  grade,
  className,
}: {
  grade: NutritionGrade | null | undefined;
  className?: string;
}) {
  if (!grade) return null;
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs text-muted-foreground", className)}
      title="Nutrition grade, A (best) to E, using the Nutri-Score method"
    >
      <span
        className={cn(
          "grid size-5 place-items-center rounded text-[11px] font-bold",
          GRADE_COLOURS[grade],
        )}
        aria-hidden
      >
        {grade}
      </span>
      <span>
        <span className="sr-only">Nutrition grade {grade} </span>
        <span aria-hidden>Nutrition grade</span>
      </span>
    </span>
  );
}

/** A product's small photo from Open Food Facts (linked, not stored); nothing for generics. */
export function ProductThumb({
  url,
  size = 40,
  className,
}: {
  url: string | null | undefined;
  size?: number;
  className?: string;
}) {
  if (!url) return null;
  return (
    // Small third-party photos of unknown size; see MealCard.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt=""
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      width={size}
      height={size}
      style={{ width: size, height: size }}
      className={cn("shrink-0 rounded-md border bg-white object-contain", className)}
    />
  );
}
