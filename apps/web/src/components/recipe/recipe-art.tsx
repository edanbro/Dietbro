import { cn } from "cn";
import {
  AppleIcon,
  BeefIcon,
  CookingPotIcon,
  DrumstickIcon,
  EggFriedIcon,
  FishIcon,
  HamIcon,
  LeafyGreenIcon,
  type LucideIcon,
  SaladIcon,
  SoupIcon,
  WheatIcon,
} from "lucide-react";
import type { CSSProperties } from "react";

/** A colour (OKLCH hue) and a drawing for each recipe category. */
const ART: Record<string, { hue: number; icon: LucideIcon }> = {
  Breakfast: { hue: 75, icon: EggFriedIcon },
  Snack: { hue: 30, icon: AppleIcon },
  Starter: { hue: 55, icon: SoupIcon },
  Beef: { hue: 25, icon: BeefIcon },
  Lamb: { hue: 15, icon: BeefIcon },
  Pork: { hue: 5, icon: HamIcon },
  Chicken: { hue: 60, icon: DrumstickIcon },
  Seafood: { hue: 230, icon: FishIcon },
  Pasta: { hue: 90, icon: WheatIcon },
  Vegetarian: { hue: 140, icon: SaladIcon },
  Vegan: { hue: 150, icon: LeafyGreenIcon },
  Side: { hue: 110, icon: SaladIcon },
  Dessert: { hue: 345, icon: AppleIcon },
};
const DEFAULT = { hue: 155, icon: CookingPotIcon };

type RecipeLike = { name: string; category: string | null; image_url: string | null };

/**
 * A recipe's photo, or, when it has none (our own recipes), a tile in its category's colour
 * with a drawing of the category, so cards never show a grey hole.
 */
export function RecipeArt({
  recipe,
  className,
  alt = "",
  eager = false,
}: {
  recipe: RecipeLike;
  className?: string;
  alt?: string;
  eager?: boolean;
}) {
  if (recipe.image_url) {
    return (
      // Recipe photos come from many hosts at arbitrary sizes; a plain lazy <img> avoids
      // routing every one through the image optimizer.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={recipe.image_url}
        alt={alt}
        loading={eager ? "eager" : "lazy"}
        decoding="async"
        className={cn("bg-muted object-cover", className)}
      />
    );
  }
  const { hue, icon: Icon } = (recipe.category && ART[recipe.category]) || DEFAULT;
  return (
    <div
      data-testid="recipe-art"
      role={alt ? "img" : undefined}
      aria-label={alt || undefined}
      style={{ "--hue": hue } as CSSProperties}
      className={cn(
        "grid place-items-center bg-[linear-gradient(135deg,oklch(0.95_0.04_var(--hue)),oklch(0.88_0.07_var(--hue)))] text-[oklch(0.45_0.1_var(--hue))]",
        "dark:bg-[linear-gradient(135deg,oklch(0.3_0.04_var(--hue)),oklch(0.24_0.05_var(--hue)))] dark:text-[oklch(0.82_0.09_var(--hue))]",
        className,
      )}
    >
      <Icon aria-hidden className="size-[40%] max-h-16 max-w-16" strokeWidth={1.5} />
    </div>
  );
}
