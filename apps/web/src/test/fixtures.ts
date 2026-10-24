/** API-shaped sample data for component tests. */
import type {
  ChatMessage,
  ChatOutcome,
  ChatThread,
  Me,
  Meal,
  Plan,
  PlanDay,
  Receipt,
  ReceiptLine,
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
    expiring_soon: 0,
  },
  setup_complete: true,
  region: {
    country: "GB",
    name: "United Kingdom",
    currency: "GBP",
    locale: "en-GB",
    timezone: "Europe/London",
    units: "metric",
    saved: true,
  },
};

export function meal(
  slot: Slot,
  id: number,
  name: string,
  { portions = 2, image = null as string | null, minutes = null as number | null } = {},
): Meal {
  return {
    slot,
    recipe: { id, name, category: null, cuisine: null, image_url: image, minutes },
    portions,
    servings: portions / 2,
    nutrition: { kcal: 600, protein_g: 30, fat_g: 20, carbs_g: 70 },
    locked: false,
    status: "planned",
    uses_pantry: [],
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
    logged: [],
  }));
  return {
    id: 7,
    version: 1,
    parent_id: null,
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
    household: 1,
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
    stocked: false,
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
    household: 1,
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
    generated: false,
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
      {
        name: "Onion",
        measure: "1 large",
        food_id: 1,
        food_name: "Onions, raw",
        grams: 150,
        in_pantry: true,
      },
      {
        name: "Eggs",
        measure: "4",
        food_id: 2,
        food_name: "Egg, whole, raw",
        grams: 200,
        in_pantry: false,
      },
      {
        name: "Feta",
        measure: "",
        food_id: null,
        food_name: null,
        grams: null,
        in_pantry: false,
      },
    ],
    ...overrides,
  };
}

// --- chat -------------------------------------------------------------------------------------

export function chatMessage(
  id: number,
  role: ChatMessage["role"],
  text: string,
  overrides: Partial<ChatMessage> = {},
): ChatMessage {
  return {
    id,
    role,
    text,
    created_at: "2026-10-09T09:00:00Z",
    plan_id: null,
    mode: role === "assistant" ? "offline" : null,
    offline_reason: null,
    attachments: [],
    suggestions: [],
    ...overrides,
  };
}

export function makeThread(overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    thread_id: 3,
    messages: [],
    has_more: false,
    pending: null,
    llm_available: true,
    offline_reason: null,
    llm_resets_at: null,
    messages_today: 0,
    daily_limit: 60,
    ...overrides,
  };
}

/** Skipping Friday's dinner (2026-10-09) in plan 7 made version 2 (plan 8). */
export function makeOutcome(overrides: Partial<ChatOutcome> = {}): ChatOutcome {
  return {
    type: "outcome",
    plan_id: 8,
    version: 2,
    fresh: false,
    results: [
      {
        index: 0,
        intent: "skip",
        date: "2026-10-09",
        slot: "dinner",
        status: "applied",
        message: "Skipped tonight's dinner.",
      },
    ],
    changes: [
      {
        date: "2026-10-09",
        slot: "dinner",
        before: "Dinner 1",
        after: null,
        reason: "skip",
        change_index: 0,
      },
      {
        date: "2026-10-10",
        slot: "lunch",
        before: "Lunch 2",
        after: "Lunch 2",
        before_portions: 2,
        after_portions: 3,
        reason: "resize",
      },
    ],
    logged: [
      {
        date: "2026-10-09",
        slot: "dinner",
        kind: "skipped",
        description: "",
        kcal: 0,
        estimated: true,
      },
    ],
    days: [],
    warnings: [],
    notes: [],
    ...overrides,
  };
}

// --- receipts (M6) ----------------------------------------------------------------------------

export function receiptLine(
  id: number,
  overrides: Partial<ReceiptLine> & Pick<ReceiptLine, "raw_text" | "name">,
): ReceiptLine {
  return {
    id,
    position: id,
    food: null,
    match_method: null,
    quantity: null,
    unit: null,
    grams: null,
    approx: false,
    price_minor: 100,
    expires_on: null,
    status: "suggested",
    pantry_item_id: null,
    ...overrides,
  };
}

const GENERIC = { kind: "food", source: "usda" } as const;
export const MILK = {
  id: 31,
  description: "Milk, reduced fat, 2%",
  category: "Dairy",
  kcal: 50,
  ...GENERIC,
};
export const TOMATOES = {
  id: 32,
  description: "Tomatoes, canned",
  category: "Vegetables",
  kcal: 20,
  ...GENERIC,
};
export const BANANA = {
  id: 33,
  description: "Bananas, raw",
  category: "Fruits",
  kcal: 89,
  ...GENERIC,
};

/** A ready pasted receipt bought 2026-10-09: milk and chopped tomatoes matched, one line not. */
export function makeReceipt(overrides: Partial<Receipt> = {}): Receipt {
  return {
    id: 5,
    source: "text",
    status: "ready",
    purchased_on: "2026-10-09",
    error: null,
    created_at: "2026-10-09T10:00:00Z",
    processed_at: "2026-10-09T10:00:01Z",
    confirmed_at: null,
    lines: [
      receiptLine(1, {
        raw_text: "SEMI SKMD MILK 4PT   £1.45",
        name: "semi skimmed milk",
        food: MILK,
        match_method: "receipt",
        quantity: 2.27,
        unit: "l",
        grams: 2340,
        expires_on: "2026-10-16",
      }),
      receiptLine(2, {
        raw_text: "CHOPPED TOMS 400G   £0.55",
        name: "chopped tomatoes",
        food: TOMATOES,
        match_method: "receipt",
        quantity: 400,
        unit: "g",
        grams: 400,
      }),
      receiptLine(3, { raw_text: "MYSTERY SNACK   £1.00", name: "mystery snack" }),
    ],
    ...overrides,
  };
}
