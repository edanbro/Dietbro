import {
  AppleIcon,
  CoffeeIcon,
  CookieIcon,
  type LucideIcon,
  SandwichIcon,
  UtensilsCrossedIcon,
} from "lucide-react";

import type { Slot } from "@/lib/api/hooks";

/** Meals of the day in eating order (mirrors larder_core.meals.SLOT_ORDER). */
export const SLOT_ORDER: readonly Slot[] = [
  "breakfast",
  "morning_snack",
  "lunch",
  "snack",
  "dinner",
  "evening_snack",
];

/** Slots every day has; snacks are by choice. */
export const REQUIRED_SLOTS: readonly Slot[] = ["breakfast", "lunch", "dinner"];

export const SLOT_LABEL: Record<Slot, string> = {
  breakfast: "Breakfast",
  morning_snack: "Morning snack",
  lunch: "Lunch",
  snack: "Snack",
  dinner: "Dinner",
  evening_snack: "Evening snack",
};

export const SLOT_ICON: Record<Slot, LucideIcon> = {
  breakfast: CoffeeIcon,
  morning_snack: AppleIcon,
  lunch: SandwichIcon,
  snack: AppleIcon,
  dinner: UtensilsCrossedIcon,
  evening_snack: CookieIcon,
};
