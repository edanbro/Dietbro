"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
