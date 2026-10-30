"use client";

import { useAuth } from "@clerk/nextjs";
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";

import { localISODate, localTime } from "@/lib/dates";
import type { Units } from "@/lib/units";
import {
  dropTicks,
  isNetworkError,
  loadSnapshot,
  pendingTicks,
  queueTick,
  saveSnapshot,
} from "@/lib/offline";

import { ApiError, unwrap, useApi } from "./browser";
import type { components } from "./schema";
import { ChangeProblemError, isChangeProblem } from "./problems";

export type Schemas = components["schemas"];
export type Me = Schemas["Me"];
export type Region = Schemas["RegionOut"];
export type RegionIn = Schemas["RegionIn"];
export type RegionOption = Schemas["RegionOption"];
export type GoalsIn = Schemas["GoalsIn"];
export type BodyIn = Schemas["BodyIn"];
export type BodyOut = Schemas["BodyOut"];
export type PreferencesIn = Schemas["PreferencesIn"];
export type QuickNightsIn = Schemas["QuickNightsIn"];
export type MealsIn = Schemas["MealsIn"];
export type MealStyle = Schemas["MealStyleIn"]["meal_style"];
export type AllergiesIn = Schemas["AllergiesIn"];
export type FoodSummary = Schemas["FoodSummary"];
export type FoodDetail = Schemas["FoodDetail"];
export type PantryItem = Schemas["PantryItemOut"];
export type PantryItemIn = Schemas["PantryItemIn"];
export type PantryItemPatch = Schemas["PantryItemPatch"];
export type Plan = Schemas["PlanOut"];
export type PlanDay = Schemas["DayOut"];
export type Meal = Schemas["MealOut"];
export type Slot = Schemas["Slot"];
export type Macros = Schemas["MacrosOut"];
export type NutrientBands = Schemas["NutrientBands"];
export type ReferenceIntakes = Schemas["ReferenceIntakes"];
export type Violation = Schemas["ViolationOut"];
export type ShoppingList = Schemas["ShoppingListOut"];
export type ShoppingItem = Schemas["ShoppingItemOut"];
export type ShoppingExtra = Schemas["ShoppingExtraOut"];
export type Recipe = Schemas["RecipeDetail"];
export type OwnMeal = Schemas["OwnMealOut"];
export type LoggedEntry = Schemas["MealLogOut"];
/** What a plan change did: results per change, changed meals, logged food, off-target days. */
export type PlanOutcome = Schemas["OutcomeOut"];
export type SlotChange = Schemas["SlotChange"];
export type Eaten = Schemas["EatenOut"];
export type PantryChange = Schemas["PantryChangeOut"];
/** A typed plan change (skip, swap, off-plan food, craving), as the replan executor takes it. */
export type PlanChange = Schemas["ReplanRequest"]["changes"][number];
export type PlanTemplate = Schemas["TemplateOut"];
export type DayMeal = Schemas["DayMealOut"];
/** A fresh plan from `start`, or the same meals again: an earlier week's or a template's. */
export type CreatePlanArgs = { start?: string; repeat_from?: string; template_id?: number };
export type ExpiringPantry = Schemas["ExpiringPantry"];
export type ExpiringItem = Schemas["ExpiringItem"];
export type Receipt = Schemas["ReceiptOut"];
export type ReceiptLine = Schemas["ReceiptLineOut"];
export type ReceiptLinePatch = Schemas["ReceiptLinePatch"];
export type ReceiptSummary = Schemas["ReceiptSummary"];
export type ReceiptStatus = Receipt["status"];
export type Diary = Schemas["DiaryOut"];
export type DiaryDay = Schemas["DiaryDayOut"];
export type Weight = Schemas["WeightOut"];
export type RecipeListItem = Schemas["RecipeListItem"];
export type RecipeList = Schemas["RecipeListOut"];
export type RecipeVerdict = Schemas["RecipeFeedbackIn"]["verdict"];
export type RecipeQuery = {
  q: string;
  slot: Slot | null;
  favourites: boolean;
  /** Only recipes known to take at most this long. */
  maxMinutes?: number | null;
  /** What can be cooked from the pantry: fewest foods still to get first. */
  pantry?: boolean;
  /** The lowest cost a serving first. */
  cheapest?: boolean;
};

export const keys = {
  me: ["me"] as const,
  goals: ["me", "goals"] as const,
  body: ["me", "body"] as const,
  preferences: ["me", "preferences"] as const,
  allergies: ["me", "allergies"] as const,
  /** Also the prefix of the expiry alerts, so every pantry change refreshes them. */
  pantry: ["pantry"] as const,
  expiring: (today: string) => ["pantry", "expiring", today] as const,
  receipts: ["receipts"] as const,
  receipt: (id: number) => ["receipts", id] as const,
  allergens: ["allergens"] as const,
  cuisines: ["cuisines"] as const,
  regions: ["regions"] as const,
  shoppingExtras: ["shopping", "extras"] as const,
  shoppingUsuals: ["shopping", "usuals"] as const,
  food: (id: number) => ["food", id] as const,
  search: (q: string, scope: string = "all") => ["foods", "search", q, scope] as const,
  currentPlan: ["plans", "current"] as const,
  upcomingPlan: ["plans", "upcoming"] as const,
  alternatives: (planId: number, date: string, slot: string) =>
    ["plans", planId, "alternatives", date, slot] as const,
  shopping: (planId: number) => ["plans", planId, "shopping"] as const,
  recipe: (id: number) => ["recipes", id] as const,
  /** Under `recipes`: feedback on any recipe refreshes every list and the detail. */
  recipeList: (query: RecipeQuery) => ["recipes", "list", query] as const,
  /** Every plan query (current plan, shopping lists): what a replan makes stale. */
  plans: ["plans"] as const,
  /** Under `plans`: marking meals eaten and logged food change it. */
  diary: (days: number) => ["plans", "diary", days] as const,
  /** Under `plans`: logging food (a plan change) adds to it. */
  recentFoods: ["plans", "recent-foods"] as const,
  weights: ["me", "weights"] as const,
  templates: ["me", "templates"] as const,
  /** Under `plans`: what a plan change makes stale. */
  mealsOn: (date: string) => ["plans", "meals", date] as const,
  /** Under `plans`: tomorrow's prep follows plan changes (and refetches on the plan page). */
  prepAhead: ["plans", "ahead"] as const,
  /** Mutations that change the current plan from the plan screen (one at a time). */
  planChange: ["plan-change"] as const,
};

export function useMe() {
  const api = useApi();
  const { userId } = useAuth();
  return useQuery({
    queryKey: keys.me,
    initialData: () => loadSnapshot<Me>(userId, "me"),
    initialDataUpdatedAt: 0,
    queryFn: async () => {
      const me = unwrap(await api.GET("/me"));
      saveSnapshot(userId, "me", me);
      return me;
    },
  });
}

/** How the user reads weights and heights (lib/units.ts): metric until /me says otherwise. */
export function useUnits(): Units {
  return useMe().data?.region.units ?? "metric";
}

export function useGoals() {
  const api = useApi();
  return useQuery({
    queryKey: keys.goals,
    queryFn: async () => unwrap(await api.GET("/me/goals")),
  });
}

export function useBody() {
  const api = useApi();
  return useQuery({ queryKey: keys.body, queryFn: async () => unwrap(await api.GET("/me/body")) });
}

export function usePreferences() {
  const api = useApi();
  return useQuery({
    queryKey: keys.preferences,
    queryFn: async () => unwrap(await api.GET("/me/preferences")),
  });
}

export function useAllergies() {
  const api = useApi();
  return useQuery({
    queryKey: keys.allergies,
    queryFn: async () => unwrap(await api.GET("/me/allergies")),
  });
}

export function useAllergens() {
  const api = useApi();
  return useQuery({
    queryKey: keys.allergens,
    queryFn: async () => unwrap(await api.GET("/allergens")),
    staleTime: Infinity,
  });
}

export function useCuisines() {
  const api = useApi();
  return useQuery({
    queryKey: keys.cuisines,
    queryFn: async () => unwrap(await api.GET("/cuisines")),
    staleTime: Infinity,
  });
}

export function usePantry() {
  const api = useApi();
  return useQuery({ queryKey: keys.pantry, queryFn: async () => unwrap(await api.GET("/pantry")) });
}

export function useFood(id: number | null) {
  const api = useApi();
  return useQuery({
    queryKey: keys.food(id ?? 0),
    enabled: id !== null,
    queryFn: async () =>
      unwrap(await api.GET("/foods/{food_id}", { params: { path: { food_id: id ?? 0 } } })),
  });
}

/** A product by barcode (catalogue, else Open Food Facts); primes the food's detail. */
export function useBarcodeLookup() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (code: string) =>
      unwrap(await api.GET("/foods/barcode/{code}", { params: { path: { code } } })),
    onSuccess: (food) => qc.setQueryData(keys.food(food.id), food),
  });
}

export const SEARCH_PAGE = 20;
export type FoodScope = "all" | "generic";

/** Pages of food search results; a full page means there may be more. */
export function useFoodSearch(q: string, scope: FoodScope = "all") {
  const api = useApi();
  const query = q.trim();
  return useInfiniteQuery({
    queryKey: keys.search(query, scope),
    enabled: query.length >= 2,
    staleTime: 60_000,
    initialPageParam: 0,
    getNextPageParam: (last: FoodSummary[], _all, offset: number) =>
      last.length === SEARCH_PAGE && offset + SEARCH_PAGE <= 200 ? offset + SEARCH_PAGE : undefined,
    queryFn: async ({ signal, pageParam }) =>
      unwrap(
        await api.GET("/foods/search", {
          params: { query: { q: query, scope, limit: SEARCH_PAGE, offset: pageParam } },
          signal,
        }),
      ),
  });
}

/** Mutations invalidate what they change plus `me` (setup status). */
function useSave<TBody, TOut>(save: (body: TBody) => Promise<TOut>, key: readonly unknown[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: save,
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: key }),
        qc.invalidateQueries({ queryKey: keys.me }),
      ]);
    },
  });
}

export function useSaveGoals() {
  const api = useApi();
  return useSave(async (body: GoalsIn) => unwrap(await api.PUT("/me/goals", { body })), keys.goals);
}

export function useSaveBody() {
  const api = useApi();
  return useSave(async (body: BodyIn) => unwrap(await api.PUT("/me/body", { body })), keys.body);
}

export function useDeleteBody() {
  const api = useApi();
  return useSave(async () => unwrap(await api.DELETE("/me/body")), keys.body);
}

export function useSavePreferences() {
  const api = useApi();
  return useSave(
    async (body: PreferencesIn) => unwrap(await api.PUT("/me/preferences", { body })),
    keys.preferences,
  );
}

/** Busy nights: the weekdays whose dinner the planner keeps quick. */
export function useSaveQuickNights() {
  const api = useApi();
  return useSave(
    async (body: QuickNightsIn) =>
      unwrap(await api.PUT("/me/preferences/quick-nights", { body })),
    keys.preferences,
  );
}

export function useSaveMeals() {
  const api = useApi();
  return useSave(
    async (body: MealsIn) => unwrap(await api.PUT("/me/preferences/meals", { body })),
    keys.preferences,
  );
}

export function useSaveMealStyle() {
  const api = useApi();
  return useSave(
    async (meal_style: MealStyle) =>
      unwrap(await api.PUT("/me/preferences/meal-style", { body: { meal_style } })),
    keys.preferences,
  );
}

/** Several items on the user's own list at once (a recipe's ingredients); returns those added. */
export function useAddShoppingExtras() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (names: string[]) =>
      unwrap(await api.POST("/shopping/extras/batch", { body: { names } })),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.shoppingExtras }),
  });
}

export type AheadItem = Schemas["AheadItemOut"];

/** What tomorrow's meals need doing tonight: food to defrost, steps to start. */
export function usePrepAhead() {
  const api = useApi();
  return useQuery({
    queryKey: keys.prepAhead,
    queryFn: async () => unwrap(await api.GET("/plans/ahead")),
  });
}

export function useRegions() {
  const api = useApi();
  return useQuery({
    queryKey: keys.regions,
    queryFn: async () => unwrap(await api.GET("/regions")),
    staleTime: Infinity,
  });
}

/** Saving a region can switch the goals' currency, and prices everywhere follow it. */
export function useSaveRegion() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: RegionIn) => unwrap(await api.PUT("/me/region", { body })),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: keys.me }),
        qc.invalidateQueries({ queryKey: keys.goals }),
      ]);
    },
  });
}

export function useSaveAllergies() {
  const api = useApi();
  return useSave(
    async (body: AllergiesIn) => unwrap(await api.PUT("/me/allergies", { body })),
    keys.allergies,
  );
}

export function useAddPantryItem() {
  const api = useApi();
  return useSave(
    async (body: PantryItemIn) => unwrap(await api.POST("/pantry", { body })),
    keys.pantry,
  );
}

export function useUpdatePantryItem() {
  const api = useApi();
  return useSave(
    async ({ id, ...body }: PantryItemPatch & { id: number }) =>
      unwrap(await api.PATCH("/pantry/{item_id}", { params: { path: { item_id: id } }, body })),
    keys.pantry,
  );
}

export function useConfirmPantryItem() {
  const api = useApi();
  return useSave(
    async (id: number) =>
      unwrap(await api.POST("/pantry/{item_id}/confirm", { params: { path: { item_id: id } } })),
    keys.pantry,
  );
}

export function useDeletePantryItem() {
  const api = useApi();
  return useSave(
    async (id: number) =>
      unwrap(await api.DELETE("/pantry/{item_id}", { params: { path: { item_id: id } } })),
    keys.pantry,
  );
}

export function useExport() {
  const api = useApi();
  return useMutation({ mutationFn: async () => unwrap(await api.GET("/me/export")) });
}

export function useDeleteAccount() {
  const api = useApi();
  return useMutation({ mutationFn: async () => unwrap(await api.DELETE("/me")) });
}

// --- plans (M3) -------------------------------------------------------------------------------

/** The plan in force today, or null before the first one. Offline: the last copy seen. */
export function useCurrentPlan() {
  const api = useApi();
  const { userId } = useAuth();
  return useQuery({
    queryKey: keys.currentPlan,
    initialData: () => loadSnapshot<Plan>(userId, "plan"),
    initialDataUpdatedAt: 0, // always refetched when online
    queryFn: async (): Promise<Plan | null> => {
      const plan = unwrap(await api.GET("/plans/current")) ?? null;
      saveSnapshot(userId, "plan", plan ?? undefined);
      return plan;
    },
  });
}

/** The plan for the days after the current one ("next week"), if made. */
export function useUpcomingPlan(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: keys.upcomingPlan,
    enabled,
    queryFn: async (): Promise<Plan | null> => unwrap(await api.GET("/plans/upcoming")) ?? null,
  });
}

/**
 * Plan a week starting today (the user's local date), replacing the current plan; or, with a
 * later `start`, next week's plan beside this one.
 */
export function useCreatePlan() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args?: string | CreatePlanArgs) => {
      const { start, ...from } = typeof args === "string" ? { start: args } : (args ?? {});
      return unwrap(
        await api.POST("/plans", { body: { start: start ?? localISODate(), ...from } }),
      );
    },
    onSuccess: async (plan, args) => {
      const start = typeof args === "string" ? args : args?.start;
      if (start && start > localISODate()) {
        await qc.invalidateQueries({ queryKey: keys.upcomingPlan });
        return;
      }
      // A refetch that started before the POST would bring back the old plan.
      await qc.cancelQueries({ queryKey: keys.currentPlan });
      qc.setQueryData(keys.currentPlan, plan);
    },
  });
}

/** A few safe recipes to swap a planned meal for (fetched when `enabled`). */
export type SwapFilters = {
  q: string;
  quick: boolean;
  pantry: boolean;
  favourites: boolean;
  cheaper: boolean;
};
const NO_FILTERS: SwapFilters = {
  q: "",
  quick: false,
  pantry: false,
  favourites: false,
  cheaper: false,
};

/** Recipes to swap a meal for: a few suggestions, or up to 6 for a search or filter. */
export function useAlternatives(
  planId: number,
  date: string,
  slot: Slot,
  enabled: boolean,
  filters: SwapFilters = NO_FILTERS,
) {
  const api = useApi();
  const filtered = Boolean(
    filters.q || filters.quick || filters.pantry || filters.favourites || filters.cheaper,
  );
  return useQuery({
    queryKey: [...keys.alternatives(planId, date, slot), filters],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(
        await api.GET("/plans/{plan_id}/alternatives", {
          params: {
            path: { plan_id: planId },
            query: { date, slot, limit: filtered ? 6 : 3, ...filters },
          },
        }),
      ),
  });
}

/** Bring back the plan as it was before its last change. */
export function useUndoPlan() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: keys.planChange,
    mutationFn: async (planId: number) =>
      unwrap(await api.POST("/plans/{plan_id}/undo", { params: { path: { plan_id: planId } } })),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.plans }),
  });
}

/** A plan's shopping list. Offline: the last copy seen, with ticks made since. */
export function useShoppingList(planId: number | null) {
  const api = useApi();
  const { userId } = useAuth();
  const what = `shopping:${planId ?? 0}`;
  return useQuery({
    queryKey: keys.shopping(planId ?? 0),
    enabled: planId !== null,
    initialData: () => loadSnapshot<ShoppingList>(userId, what),
    initialDataUpdatedAt: 0,
    queryFn: async () => {
      const list = unwrap(
        await api.GET("/plans/{plan_id}/shopping", {
          params: { path: { plan_id: planId ?? 0 } },
        }),
      );
      saveSnapshot(userId, what, list);
      return list;
    },
  });
}

type Tick = { item: ShoppingItem; checked: boolean };

function withChecked(list: ShoppingList | undefined, foodId: number, checked: boolean) {
  if (!list) return list;
  return {
    ...list,
    items: list.items.map((i) => (i.food_id === foodId ? { ...i, checked } : i)),
  };
}

/**
 * Tick a shopping line. Optimistic: the box flips at once. Requests for one plan run one at a
 * time (mutation scope) so rapid taps reach the server in order. On failure only that line is
 * restored (unless a later tap changed it again) and a toast says so. The list is refetched
 * once the last queued tick settles, never in between (that would flicker).
 */
export function useTickShoppingItem(planId: number) {
  const api = useApi();
  const qc = useQueryClient();
  const { userId } = useAuth();
  const key = keys.shopping(planId);
  const mutationKey = ["shopping-tick", planId];
  return useMutation({
    mutationKey,
    scope: { id: `shopping-${planId}` },
    mutationFn: async ({ item, checked }: Tick) => {
      try {
        return unwrap(
          await api.PATCH("/plans/{plan_id}/shopping/{food_id}", {
            params: { path: { plan_id: planId, food_id: item.food_id } },
            body: { checked },
          }),
        );
      } catch (error) {
        // In a shop with no signal: keep the tick and send it when back online.
        if (!userId || !isNetworkError(error)) throw error;
        queueTick(userId, { planId, foodId: item.food_id, checked });
        if (pendingTicks(userId).length === 1) {
          toast("You're offline. Ticks are saved and will sync when you're back online.");
        }
        return null;
      }
    },
    onMutate: async ({ item, checked }: Tick) => {
      await qc.cancelQueries({ queryKey: key });
      qc.setQueryData<ShoppingList>(key, (list) => {
        const next = withChecked(list, item.food_id, checked);
        saveSnapshot(userId, `shopping:${planId}`, next);
        return next;
      });
    },
    onError: (_error, { item, checked }) => {
      qc.setQueryData<ShoppingList>(key, (list) => {
        const now = list?.items.find((i) => i.food_id === item.food_id);
        return now?.checked === checked ? withChecked(list, item.food_id, !checked) : list;
      });
      toast.error(`Couldn't update ${item.name}. Try again.`);
    },
    onSettled: async () => {
      // This mutation still counts as running here, so 1 means "the last one".
      if (qc.isMutating({ mutationKey }) === 1) await qc.invalidateQueries({ queryKey: key });
    },
  });
}

/**
 * Send shopping ticks made offline once the connection is back (on load and on "online").
 * A tick the server refuses (the plan changed meanwhile) is dropped; the list is refetched.
 */
export function useOfflineSync() {
  const api = useApi();
  const qc = useQueryClient();
  const { userId } = useAuth();
  useEffect(() => {
    if (!userId) return;
    let running = false;
    const flush = async () => {
      const ticks = pendingTicks(userId);
      if (running || !ticks.length || !navigator.onLine) return;
      running = true;
      const done: typeof ticks = [];
      try {
        for (const t of ticks) {
          try {
            unwrap(
              await api.PATCH("/plans/{plan_id}/shopping/{food_id}", {
                params: { path: { plan_id: t.planId, food_id: t.foodId } },
                body: { checked: t.checked },
              }),
            );
          } catch (error) {
            if (isNetworkError(error)) break; // still offline: try again later
          }
          done.push(t);
        }
      } finally {
        dropTicks(userId, done);
        running = false;
      }
      if (done.length) {
        await qc.invalidateQueries({ queryKey: keys.plans });
        toast.success("Shopping list synced");
      }
    };
    void flush();
    window.addEventListener("online", flush);
    return () => window.removeEventListener("online", flush);
  }, [api, qc, userId]);
}

/** Move bought lines into the pantry (default: every ticked line not moved yet). */
export function useStockShopping(planId: number) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (foodIds?: number[]) =>
      unwrap(
        await api.POST("/plans/{plan_id}/shopping/stock", {
          params: { path: { plan_id: planId } },
          body: { food_ids: foodIds ?? null },
        }),
      ),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: keys.shopping(planId) }),
        qc.invalidateQueries({ queryKey: keys.pantry }),
        qc.invalidateQueries({ queryKey: keys.me }),
      ]);
    },
  });
}

export function useShoppingExtras() {
  const api = useApi();
  return useQuery({
    queryKey: keys.shoppingExtras,
    queryFn: async () => unwrap(await api.GET("/shopping/extras")),
  });
}

/** What the user buys most weeks, from their receipts (offered on the list in one tap). */
export function useShoppingUsuals() {
  const api = useApi();
  return useQuery({
    queryKey: keys.shoppingUsuals,
    staleTime: 60 * 60 * 1000,
    queryFn: async () => unwrap(await api.GET("/shopping/usuals")),
  });
}

/** Add, tick, delete or clear the user's own shopping items (one hook, `action` picks). */
export function useShoppingExtra() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (
      action:
        | { kind: "add"; name: string }
        | { kind: "tick"; id: number; checked: boolean }
        | { kind: "delete"; id: number }
        | { kind: "clear" },
    ) => {
      switch (action.kind) {
        case "add":
          return unwrap(await api.POST("/shopping/extras", { body: { name: action.name } }));
        case "tick":
          return unwrap(
            await api.PATCH("/shopping/extras/{extra_id}", {
              params: { path: { extra_id: action.id } },
              body: { checked: action.checked },
            }),
          );
        case "delete":
          return unwrap(
            await api.DELETE("/shopping/extras/{extra_id}", {
              params: { path: { extra_id: action.id } },
            }),
          );
        case "clear":
          return unwrap(await api.DELETE("/shopping/extras"));
      }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: keys.shoppingExtras }),
  });
}

export function useRecipe(id: number) {
  const api = useApi();
  return useQuery({
    queryKey: keys.recipe(id),
    staleTime: 5 * 60_000,
    queryFn: async () =>
      unwrap(await api.GET("/recipes/{recipe_id}", { params: { path: { recipe_id: id } } })),
  });
}

/** Several recipes at once (meal prep), each cached like useRecipe's. */
export function useRecipes(ids: number[]) {
  const api = useApi();
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: keys.recipe(id),
      staleTime: 5 * 60_000,
      queryFn: async () =>
        unwrap(await api.GET("/recipes/{recipe_id}", { params: { path: { recipe_id: id } } })),
    })),
  });
}

// --- plan-screen changes (M5) -----------------------------------------------------------------

/** A meal on the plan: the plan cell an eaten mark or a change is about. */
export type MealCell = { date: string; slot: Slot };

/** What a plan conflict (409) means for the user; the plan is reloaded either way. */
function conflictMessage(error: ApiError): string {
  const code = error instanceof ChangeProblemError ? error.code : null;
  if (code === "busy") {
    return "Another change to your plan is still running. Try again in a moment.";
  }
  if (code === "duplicate") return "That change was already made. Showing your latest plan.";
  return "Your plan changed in the meantime. Showing the latest version.";
}

/**
 * After a plan-screen change: the plan (and its shopping list) and the pantry are stale.
 * Errors get a toast; conflicts and missing meals reload the plan first.
 */
function usePlanChangeHandlers() {
  const qc = useQueryClient();
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: keys.plans }),
      qc.invalidateQueries({ queryKey: keys.pantry }),
    ]);
  return {
    onSuccess: refresh,
    onError: (error: Error) => {
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) {
        void refresh();
        toast.error(
          error.status === 404
            ? "That meal isn't in your plan any more. Showing your latest plan."
            : conflictMessage(error),
        );
        return;
      }
      toast.error(error.message || "Couldn't update your plan. Try again.");
    },
  };
}

/** Mark a planned meal eaten (on or before today), or undo the mark. */
export function useMarkEaten(planId: number) {
  const api = useApi();
  return useMutation({
    mutationKey: keys.planChange,
    mutationFn: async ({ date, slot, undo }: MealCell & { undo: boolean }): Promise<Eaten> => {
      const path = { plan_id: planId };
      return undo
        ? unwrap(
            await api.DELETE("/plans/{plan_id}/meals/eaten", {
              params: { path, query: { date, slot } },
            }),
          )
        : unwrap(
            await api.POST("/plans/{plan_id}/meals/eaten", {
              params: { path },
              body: { today: localISODate(), date, slot },
            }),
          );
    },
    ...usePlanChangeHandlers(),
  });
}

/**
 * Re-plan around typed changes. Each call gets its own client id (the API
 * answers a resend with 409 duplicate); `today` and the local time come from this device.
 */
export function useReplan() {
  const api = useApi();
  return useMutation({
    mutationKey: keys.planChange,
    mutationFn: async (changes: PlanChange[]): Promise<PlanOutcome> => {
      const result = await api.POST("/plans/replan", {
        body: {
          changes,
          client_id: crypto.randomUUID(),
          today: localISODate(),
          local_time: localTime(),
        },
      });
      // busy / duplicate / bad_today come as problems with a code.
      if (isChangeProblem(result.error)) {
        throw new ChangeProblemError(result.response.status, result.error);
      }
      return unwrap(result);
    },
    ...usePlanChangeHandlers(),
  });
}

export type FoodLogItem = { food_id: number; grams: number };

/**
 * Log food picked from search or a barcode, with exact grams (diary quick-add). The API runs it
 * through the replan executor as food eaten off-plan, so the rest of that day's plan rebalances.
 */
export function useLogFood() {
  const api = useApi();
  return useMutation({
    mutationKey: keys.planChange,
    mutationFn: async ({
      items,
      slot,
      date = localISODate(),
    }: {
      items: FoodLogItem[];
      slot: Slot | null;
      date?: string;
    }): Promise<PlanOutcome> => {
      const result = await api.POST("/diary/log", {
        body: {
          eaten_on: date,
          slot,
          items,
          client_id: crypto.randomUUID(),
          today: localISODate(),
          local_time: localTime(),
        },
      });
      if (isChangeProblem(result.error)) {
        throw new ChangeProblemError(result.response.status, result.error);
      }
      return unwrap(result);
    },
    ...usePlanChangeHandlers(),
  });
}

/** Foods and grams from what the user typed, for them to check; nothing is logged yet. */
export function useParseFoodText() {
  const api = useApi();
  return useMutation({
    mutationFn: async (text: string) =>
      unwrap(await api.POST("/diary/parse", { body: { text, today: localISODate() } })),
  });
}

// --- pantry intake (M6) -----------------------------------------------------------------------

/** Pantry items expired or expiring within `days` of the user's local today, soonest first. */
export function useExpiring(days = 3) {
  const api = useApi();
  const today = localISODate();
  return useQuery({
    queryKey: [...keys.expiring(today), days],
    queryFn: async () =>
      unwrap(await api.GET("/pantry/expiring", { params: { query: { days, today } } })),
  });
}

/** The worker hasn't finished reading this receipt yet. */
export function isReading(status: ReceiptStatus | undefined): boolean {
  return status === "queued" || status === "processing";
}

export function useReceipts() {
  const api = useApi();
  return useQuery({
    queryKey: keys.receipts,
    queryFn: async () => unwrap(await api.GET("/pantry/receipts")),
  });
}

/**
 * One receipt. While the worker reads it (queued/processing) and `poll` is on, it is refetched
 * every half second for pasted text and every 1.5 s for photos (OCR takes about that long);
 * polling stops on ready, failed or confirmed.
 */
export function useReceipt(id: number, { poll = true }: { poll?: boolean } = {}) {
  const api = useApi();
  return useQuery({
    queryKey: keys.receipt(id),
    queryFn: async () =>
      unwrap(
        await api.GET("/pantry/receipts/{upload_id}", { params: { path: { upload_id: id } } }),
      ),
    refetchInterval: (query) => {
      const receipt = query.state.data;
      if (!poll || !receipt || !isReading(receipt.status)) return false;
      return receipt.source === "text" ? 500 : 1500;
    },
  });
}

/** Seed the receipt's cache with the 202 answer, so its page starts polling from there. */
function useReceiptCreated() {
  const qc = useQueryClient();
  return async (receipt: Receipt) => {
    qc.setQueryData(keys.receipt(receipt.id), receipt);
    await qc.invalidateQueries({ queryKey: keys.receipts, exact: true });
  };
}

export function useSubmitReceiptText() {
  const api = useApi();
  const onSuccess = useReceiptCreated();
  return useMutation({
    mutationFn: async (body: Schemas["ReceiptTextIn"]) =>
      unwrap(await api.POST("/pantry/receipts/text", { body })),
    onSuccess,
  });
}

export function useUploadReceiptImage() {
  const api = useApi();
  const onSuccess = useReceiptCreated();
  return useMutation({
    mutationFn: async ({ file, purchased_on }: { file: File; purchased_on?: string }) =>
      unwrap(
        await api.POST("/pantry/receipts/image", {
          // The schema types the file as a string; it goes as multipart form data.
          body: { file: "", purchased_on },
          bodySerializer: () => {
            const form = new FormData();
            form.append("file", file, file.name);
            if (purchased_on) form.append("purchased_on", purchased_on);
            return form;
          },
        }),
      ),
    onSuccess,
  });
}

/** Edit one suggested line; the answer replaces that line in the cached receipt. */
export function useUpdateReceiptLine(receiptId: number) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ lineId, patch }: { lineId: number; patch: ReceiptLinePatch }) =>
      unwrap(
        await api.PATCH("/pantry/receipts/{upload_id}/lines/{line_id}", {
          params: { path: { upload_id: receiptId, line_id: lineId } },
          body: patch,
        }),
      ),
    onSuccess: (line) => {
      qc.setQueryData<Receipt>(keys.receipt(receiptId), (receipt) =>
        receipt
          ? { ...receipt, lines: receipt.lines.map((l) => (l.id === line.id ? line : l)) }
          : receipt,
      );
    },
    onError: (error) => {
      // 409: the receipt isn't reviewable any more (confirmed elsewhere); show what it is now.
      if (error instanceof ApiError && error.status === 409) {
        void qc.invalidateQueries({ queryKey: keys.receipt(receiptId) });
      }
    },
  });
}

/** Add the reviewed lines to the pantry; pantry, expiry alerts, receipts and `me` go stale. */
export function useConfirmReceipt(receiptId: number) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/pantry/receipts/{upload_id}/confirm", {
          params: { path: { upload_id: receiptId } },
        }),
      ),
    onSuccess: async ({ receipt }) => {
      qc.setQueryData(keys.receipt(receiptId), receipt);
      await Promise.all([
        qc.invalidateQueries({ queryKey: keys.pantry }),
        qc.invalidateQueries({ queryKey: keys.receipts, exact: true }),
        qc.invalidateQueries({ queryKey: keys.me }),
      ]);
    },
  });
}

export function useDeleteReceipt() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) =>
      unwrap(
        await api.DELETE("/pantry/receipts/{upload_id}", { params: { path: { upload_id: id } } }),
      ),
    onSuccess: async (_data, id) => {
      qc.removeQueries({ queryKey: keys.receipt(id) });
      await qc.invalidateQueries({ queryKey: keys.receipts, exact: true });
    },
  });
}

/** The last `days` days of what was eaten, against the goals (today last). */
export type ShareTarget =
  | { kind: "recipe"; recipe_id: number }
  | { kind: "week" | "list"; start: string };

/** A read-only public link to a recipe or a week (the same link when asked again). */
export function useShareLink() {
  const api = useApi();
  return useMutation({
    mutationFn: async (target: ShareTarget) =>
      unwrap(await api.POST("/share", { body: target })),
  });
}

/** Saved weeks of meals to plan from again. */
export function useTemplates(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: keys.templates,
    enabled,
    queryFn: async () => unwrap(await api.GET("/me/templates")),
  });
}

/** Save the week starting on `start` as a template. */
export function useSaveTemplate() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; start: string }) =>
      unwrap(await api.POST("/me/templates", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.templates }),
  });
}

export function useRenameTemplate() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, name }: { id: number; name: string }) =>
      unwrap(
        await api.PATCH("/me/templates/{template_id}", {
          params: { path: { template_id: id } },
          body: { name },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.templates }),
  });
}

export function useDeleteTemplate() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const result = await api.DELETE("/me/templates/{template_id}", {
        params: { path: { template_id: id } },
      });
      if (!result.response.ok) unwrap(result);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.templates }),
  });
}

/** The meals planned on `date` (to copy them to another day), fetched when `enabled`. */
export function useMealsOn(date: string, enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: keys.mealsOn(date),
    enabled: enabled && Boolean(date),
    queryFn: async () =>
      unwrap(await api.GET("/plans/meals", { params: { query: { on: date } } })),
  });
}

/** Stop a share link working. */
export function useRevokeShareLink() {
  const api = useApi();
  return useMutation({
    mutationFn: async (token: string) => {
      const result = await api.DELETE("/share/{token}", { params: { path: { token } } });
      if (!result.response.ok) unwrap(result);
    },
  });
}

export type ImportDraft = Schemas["ImportDraft"];
export type ImportResult = Schemas["ImportResultOut"];

/** Read the recipe a web page publishes into an editable draft (nothing saved yet). */
export function useReadRecipePage() {
  const api = useApi();
  return useMutation({
    mutationFn: async (url: string): Promise<ImportDraft> =>
      unwrap(await api.POST("/recipes/import/read", { body: { url } })),
  });
}

/** Check and save a draft as the user's own recipe, or get back what to fix. */
export function useImportRecipe() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (draft: ImportDraft): Promise<ImportResult> =>
      unwrap(await api.POST("/recipes/import", { body: draft })),
    onSuccess: (result) => {
      if (result.recipe_id !== null) void qc.invalidateQueries({ queryKey: ["recipes"] });
    },
  });
}

/** Save changes to a recipe: the user's own in place, a catalogue one as their copy. */
export function useEditRecipe(recipeId: number) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (draft: ImportDraft): Promise<ImportResult> =>
      unwrap(
        await api.PUT("/recipes/{recipe_id}", {
          params: { path: { recipe_id: recipeId } },
          body: draft,
        }),
      ),
    onSuccess: (result) => {
      if (result.recipe_id !== null) void qc.invalidateQueries({ queryKey: ["recipes"] });
    },
  });
}

export type RecipeNoteIn = Schemas["RecipeNoteIn"];

/** The user's private note and rating on a recipe; both empty removes it. */
export function useRecipeNote(recipeId: number) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: RecipeNoteIn) =>
      unwrap(
        await api.PUT("/recipes/{recipe_id}/note", {
          params: { path: { recipe_id: recipeId } },
          body,
        }),
      ),
    onSuccess: (note) => {
      qc.setQueryData<Recipe>(keys.recipe(recipeId), (r) => (r ? { ...r, note } : r));
    },
  });
}

export type Spending = Schemas["SpendingOut"];

/** Grocery spending from confirmed receipts per week, beside the plans' estimates. */
export function useSpending(weeks = 12) {
  const api = useApi();
  return useQuery({
    queryKey: ["spending", weeks] as const,
    queryFn: async () =>
      unwrap(await api.GET("/insights/spending", { params: { query: { weeks } } })),
  });
}

export type Recap = Schemas["RecapOut"];

/** A week looked back on: `week` is any of its days; the last full week without one. */
export function useRecap(week?: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["recap", week ?? "last"] as const,
    queryFn: async () =>
      unwrap(await api.GET("/insights/recap", { params: { query: week ? { week } : {} } })),
  });
}

export type Prices = Schemas["PricesOut"];
export type PriceItem = Prices["items"][number];

/** Per-kg prices from the user's receipts: rises and cheaper products (price watch). */
export function usePrices(months = 6) {
  const api = useApi();
  return useQuery({
    queryKey: ["prices", months] as const,
    queryFn: async () =>
      unwrap(await api.GET("/insights/prices", { params: { query: { months } } })),
  });
}

export function useDiary(days = 7) {
  const api = useApi();
  return useQuery({
    queryKey: keys.diary(days),
    queryFn: async () => unwrap(await api.GET("/diary", { params: { query: { days } } })),
  });
}

export type RecentFood = Schemas["RecentFoodOut"];

/** Food logged lately with exact amounts, to log again from quick-add. */
export function useRecentFoods(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: keys.recentFoods,
    enabled,
    queryFn: async () => unwrap(await api.GET("/diary/recent")),
  });
}

export function useWeights(days = 90) {
  const api = useApi();
  return useQuery({
    queryKey: keys.weights,
    queryFn: async () => unwrap(await api.GET("/me/weights", { params: { query: { days } } })),
  });
}

/** Record or delete a weigh-in; the newest also becomes the body profile's weight. */
/** Remove food logged by mistake (or a skip); today's or a later meal is planned again. */
export function useRemoveLog() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: keys.planChange,
    mutationFn: async (id: number) =>
      unwrap(await api.DELETE("/diary/logs/{log_id}", { params: { path: { log_id: id } } })),
    onSettled: () => qc.invalidateQueries({ queryKey: ["plans"] }),
  });
}

export function useWeight() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (
      action:
        | { kind: "save"; measured_on: string; weight_kg: number }
        | { kind: "delete"; measured_on: string },
    ) =>
      action.kind === "save"
        ? unwrap(
            await api.PUT("/me/weights", {
              body: { measured_on: action.measured_on, weight_kg: action.weight_kg },
            }),
          )
        : unwrap(
            await api.DELETE("/me/weights/{measured_on}", {
              params: { path: { measured_on: action.measured_on } },
            }),
          ),
    onSettled: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.weights }),
        qc.invalidateQueries({ queryKey: keys.body }),
      ]),
  });
}

const RECIPE_PAGE = 24;

/** Safe recipes for the user, best first, paged ("More" loads the next page). */
export function useRecipeList(query: RecipeQuery) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: keys.recipeList(query),
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/recipes", {
          params: {
            query: {
              q: query.q,
              slot: query.slot ?? undefined,
              favourites: query.favourites,
              max_minutes: query.maxMinutes ?? undefined,
              pantry: query.pantry || undefined,
              cheapest: query.cheapest || undefined,
              limit: RECIPE_PAGE,
              offset: pageParam,
            },
          },
        }),
      ),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });
}

/** Delete a recipe of the user's own (hidden instead when a plan has it). */
export function useDeleteRecipe(recipeId: number) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.DELETE("/recipes/{recipe_id}", { params: { path: { recipe_id: recipeId } } }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recipes"] }),
  });
}

/** Favourite a recipe, never plan it again, or clear the verdict (null). */
export function useRecipeFeedback(recipeId: number) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (verdict: RecipeVerdict | null) => {
      const path = { recipe_id: recipeId };
      return verdict
        ? unwrap(
            await api.PUT("/recipes/{recipe_id}/feedback", { params: { path }, body: { verdict } }),
          )
        : unwrap(await api.DELETE("/recipes/{recipe_id}/feedback", { params: { path } }));
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["recipes"] }),
  });
}
