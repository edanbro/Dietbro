"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { localISODate } from "@/lib/dates";

import { unwrap, useApi } from "./browser";
import type { components } from "./schema";

export type Schemas = components["schemas"];
export type Me = Schemas["Me"];
export type GoalsIn = Schemas["GoalsIn"];
export type BodyIn = Schemas["BodyIn"];
export type BodyOut = Schemas["BodyOut"];
export type PreferencesIn = Schemas["PreferencesIn"];
export type AllergiesIn = Schemas["AllergiesIn"];
export type FoodSummary = Schemas["FoodSummary"];
export type PantryItem = Schemas["PantryItemOut"];
export type PantryItemIn = Schemas["PantryItemIn"];
export type Plan = Schemas["PlanOut"];
export type PlanDay = Schemas["DayOut"];
export type Meal = Schemas["MealOut"];
export type Slot = Schemas["Slot"];
export type Macros = Schemas["MacrosOut"];
export type NutrientBands = Schemas["NutrientBands"];
export type Violation = Schemas["ViolationOut"];
export type ShoppingList = Schemas["ShoppingListOut"];
export type ShoppingItem = Schemas["ShoppingItemOut"];
export type Recipe = Schemas["RecipeDetail"];

export const keys = {
  me: ["me"] as const,
  goals: ["me", "goals"] as const,
  body: ["me", "body"] as const,
  preferences: ["me", "preferences"] as const,
  allergies: ["me", "allergies"] as const,
  pantry: ["pantry"] as const,
  allergens: ["allergens"] as const,
  cuisines: ["cuisines"] as const,
  food: (id: number) => ["food", id] as const,
  search: (q: string) => ["foods", "search", q] as const,
  currentPlan: ["plans", "current"] as const,
  shopping: (planId: number) => ["plans", planId, "shopping"] as const,
  recipe: (id: number) => ["recipes", id] as const,
};

export function useMe() {
  const api = useApi();
  return useQuery({ queryKey: keys.me, queryFn: async () => unwrap(await api.GET("/me")) });
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

export function useFoodSearch(q: string) {
  const api = useApi();
  const query = q.trim();
  return useQuery({
    queryKey: keys.search(query),
    enabled: query.length >= 2,
    staleTime: 60_000,
    queryFn: async ({ signal }) =>
      unwrap(await api.GET("/foods/search", { params: { query: { q: query } }, signal })),
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

/** The latest plan, or null before the first one. */
export function useCurrentPlan() {
  const api = useApi();
  return useQuery({
    queryKey: keys.currentPlan,
    queryFn: async (): Promise<Plan | null> => unwrap(await api.GET("/plans/current")) ?? null,
  });
}

/** Plan a week starting today (the user's local date). Replaces the current plan. */
export function useCreatePlan() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST("/plans", { body: { start: localISODate() } })),
    onSuccess: async (plan) => {
      // A refetch that started before the POST would bring back the old plan.
      await qc.cancelQueries({ queryKey: keys.currentPlan });
      qc.setQueryData(keys.currentPlan, plan);
    },
  });
}

export function useShoppingList(planId: number | null) {
  const api = useApi();
  return useQuery({
    queryKey: keys.shopping(planId ?? 0),
    enabled: planId !== null,
    queryFn: async () =>
      unwrap(
        await api.GET("/plans/{plan_id}/shopping", {
          params: { path: { plan_id: planId ?? 0 } },
        }),
      ),
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
  const key = keys.shopping(planId);
  const mutationKey = ["shopping-tick", planId];
  return useMutation({
    mutationKey,
    scope: { id: `shopping-${planId}` },
    mutationFn: async ({ item, checked }: Tick) =>
      unwrap(
        await api.PATCH("/plans/{plan_id}/shopping/{food_id}", {
          params: { path: { plan_id: planId, food_id: item.food_id } },
          body: { checked },
        }),
      ),
    onMutate: async ({ item, checked }: Tick) => {
      await qc.cancelQueries({ queryKey: key });
      qc.setQueryData<ShoppingList>(key, (list) => withChecked(list, item.food_id, checked));
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

export function useRecipe(id: number) {
  const api = useApi();
  return useQuery({
    queryKey: keys.recipe(id),
    staleTime: 5 * 60_000,
    queryFn: async () =>
      unwrap(await api.GET("/recipes/{recipe_id}", { params: { path: { recipe_id: id } } })),
  });
}
