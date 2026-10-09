/** API-shaped sample data for component tests. */
import type {
  Me,
  Meal,
  Plan,
  PlanDay,
  Recipe,
  ShoppingItem,
  ShoppingList,
  Slot,
} from "@/lib/api/hooks";
import { addDays } from "@/lib/dates";

export const ME: Me = {
  id: 1,
  created_at: "2026-10-01T09:00:00Z",
  profile: {
    has_goals: true,
    has_body: false,
    has_allergies: true,
    has_preferences: true,
    pantry_items: 2,
  },
  setup_complete: true,
};

export function meal(
  slot: Slot,
  id: number,
  name: string,
  { portions = 2, image = null as string | null } = {},
): Meal {
  return {
    slot,
    recipe: { id, name, category: null, cuisine: null, image_url: image },
    portions,
    servings: portions / 2,
    nutrition: { kcal: 600, protein_g: 30, fat_g: 20, carbs_g: 70 },
    locked: false,
    status: "planned",
  };
}

/** A 7-day plan from 2026-10-09 (a Friday): "Breakfast 1", "Lunch 1", "Dinner 1" on day 1… */
export function makePlan(overrides: Partial<Plan> = {}): Plan {
  const start = overrides.start ?? "2026-10-09";
  const days: PlanDay[] = Array.from({ length: 7 }, (_, d) => ({
    day: d,
    date: addDays(start, d),
    meals: [
      meal("breakfast", 100 + d, `Breakfast ${d + 1}`, {
        portions: 3,
        image: d === 0 ? "https://img.example/b1.jpg" : null,
      }),
      meal("lunch", 200 + d, `Lunch ${d + 1}`),
      meal("dinner", 300 + d, `Dinner ${d + 1}`, { portions: 4 }),
    ],
    totals: { kcal: 1900, protein_g: 95, fat_g: 60, carbs_g: 230 },
  }));
  return {
    id: 7,
    version: 1,
    start,
    days,
    planner: "cpsat",
    status: "feasible",
    created_at: "2026-10-09T08:00:00Z",
    solve_ms: 1200,
    currency: "GBP",
    targets: {
      daily: {
        kcal: { min: 1800, max: 2200 },
        protein_g: { min: 72, max: null },
        fat_g: null,
        carbs_g: null,
      },
      weekly: { kcal: null, protein_g: { min: 630, max: null }, fat_g: null, carbs_g: null },
      calorie_floor: 1200,
    },
    week_totals: { kcal: 13300, protein_g: 665, fat_g: 420, carbs_g: 1610 },
    cost_minor: 4210,
    budget_minor: 5000,
    pantry_used_g: 1200,
    waste_g: 0,
    shopping_items: 4,
    excluded_allergens: ["peanuts"],
    diet: "vegetarian",
    violations: [],
    notes: [],
    ...overrides,
  };
}

export function item(
  overrides: Partial<ShoppingItem> & Pick<ShoppingItem, "food_id" | "name">,
): ShoppingItem {
  return {
    category: null,
    grams: 500,
    cost_minor: 100,
    checked: false,
    staple: false,
    approx_units: null,
    ...overrides,
  };
}

export function makeShoppingList(overrides: Partial<ShoppingList> = {}): ShoppingList {
  return {
    plan_id: 7,
    currency: "GBP",
    total_minor: 1234,
    budget_minor: 5000,
    items: [
      item({
        food_id: 11,
        name: "Onions, raw",
        category: "Vegetables and Vegetable Products",
        grams: 450,
        cost_minor: 60,
        approx_units: "≈ 3 medium",
      }),
      item({
        food_id: 12,
        name: "Spinach, raw",
        category: "Vegetables and Vegetable Products",
        grams: 200,
        cost_minor: 150,
      }),
      item({
        food_id: 13,
        name: "Milk, whole",
        category: "Dairy and Egg Products",
        grams: 1250,
        cost_minor: 1024,
        checked: true,
      }),
      item({
        food_id: 14,
        name: "Salt, table",
        category: "Spices and Herbs",
        grams: 0,
        cost_minor: 0,
        staple: true,
      }),
    ],
    ...overrides,
  };
}

export function makeRecipe(overrides: Partial<Recipe> = {}): Recipe {
  return {
    id: 101,
    name: "Shakshuka",
    category: "Vegetarian",
    cuisine: "Egyptian",
    image_url: "https://img.example/shakshuka.jpg",
    instructions: "Fry the onion.\r\n\r\nAdd the tomatoes and simmer.\r\nCrack in the eggs.",
    source: "mealdb",
    source_url: "https://www.bbcgoodfood.com/recipes/shakshuka",
    servings: 4,
    servings_estimated: true,
    per_serving: { kcal: 320, protein_g: 18, fat_g: 20, carbs_g: 16 },
    meal_types: ["breakfast", "lunch"],
    allergens: ["eggs", "milk"],
    allergens_complete: false,
    suitable_for: ["vegetarian"],
    ingredients: [
      { name: "Onion", measure: "1 large", food_id: 1, food_name: "Onions, raw", grams: 150 },
      { name: "Eggs", measure: "4", food_id: 2, food_name: "Egg, whole, raw", grams: 200 },
      { name: "Feta", measure: "", food_id: null, food_name: null, grams: null },
    ],
    ...overrides,
  };
}
