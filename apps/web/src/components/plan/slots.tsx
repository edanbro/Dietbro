import {
  AppleIcon,
  CoffeeIcon,
  type LucideIcon,
  SandwichIcon,
  UtensilsCrossedIcon,
} from "lucide-react";

import type { Slot } from "@/lib/api/hooks";

/** Meals of the day in eating order (mirrors larder_core.meals.SLOT_ORDER). */
export const SLOT_ORDER: readonly Slot[] = ["breakfast", "lunch", "dinner", "snack"];

/** Slots every day has; snack is optional. */
export const REQUIRED_SLOTS: readonly Slot[] = ["breakfast", "lunch", "dinner"];

export const SLOT_LABEL: Record<Slot, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snack",
};

export const SLOT_ICON: Record<Slot, LucideIcon> = {
  breakfast: CoffeeIcon,
  lunch: SandwichIcon,
  dinner: UtensilsCrossedIcon,
  snack: AppleIcon,
};
