"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { localISODate, localTime } from "@/lib/dates";

import { ApiError, unwrap, useApi } from "./browser";
import type { components } from "./schema";
import { ChatProblemError, isChatProblem } from "./sse";

export type Schemas = components["schemas"];
export type Me = Schemas["Me"];
export type Region = Schemas["RegionOut"];
export type RegionIn = Schemas["RegionIn"];
export type RegionOption = Schemas["RegionOption"];
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
export type LoggedEntry = Schemas["MealLogOut"];
export type ChatThread = Schemas["ThreadOut"];
export type ChatMessage = Schemas["ChatMessageOut"];
export type ChatAttachment = ChatMessage["attachments"][number];
export type ChatOutcome = Schemas["OutcomeOut"];
export type SlotChange = Schemas["SlotChange"];
export type OfflineReason = NonNullable<ChatThread["offline_reason"]>;
export type Eaten = Schemas["EatenOut"];
export type PantryChange = Schemas["PantryChangeOut"];
/** A typed plan change (skip, swap, off-plan food, craving), as the chat's executor takes it. */
export type PlanChange = Schemas["ReplanRequest"]["changes"][number];
export type ExpiringPantry = Schemas["ExpiringPantry"];
export type ExpiringItem = Schemas["ExpiringItem"];
export type Receipt = Schemas["ReceiptOut"];
export type ReceiptLine = Schemas["ReceiptLineOut"];
export type ReceiptLinePatch = Schemas["ReceiptLinePatch"];
export type ReceiptSummary = Schemas["ReceiptSummary"];
export type ReceiptStatus = Receipt["status"];

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
  food: (id: number) => ["food", id] as const,
  search: (q: string) => ["foods", "search", q] as const,
  currentPlan: ["plans", "current"] as const,
  shopping: (planId: number) => ["plans", planId, "shopping"] as const,
  recipe: (id: number) => ["recipes", id] as const,
  /** Every plan query (current plan, shopping lists): what a chat replan makes stale. */
  plans: ["plans"] as const,
  chatThread: ["chat", "thread"] as const,
  /** Mutations that change the current plan from the plan screen (one at a time). */
  planChange: ["plan-change"] as const,
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

// --- plan-screen changes (M5) -----------------------------------------------------------------

/** A meal on the plan: the plan cell an eaten mark or a change is about. */
export type MealCell = { date: string; slot: Slot };

/** What a plan conflict (409) means for the user; the plan is reloaded either way. */
function conflictMessage(error: ApiError): string {
  const code = error instanceof ChatProblemError ? error.code : null;
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
 * Re-plan around typed changes without the chat. Each call gets its own client id (the API
 * answers a resend with 409 duplicate); `today` and the local time come from this device.
 */
export function useReplan() {
  const api = useApi();
  return useMutation({
    mutationKey: keys.planChange,
    mutationFn: async (changes: PlanChange[]): Promise<ChatOutcome> => {
      const result = await api.POST("/plans/replan", {
        body: {
          changes,
          client_id: crypto.randomUUID(),
          today: localISODate(),
          local_time: localTime(),
        },
      });
      // busy / duplicate / bad_today come as the chat's problems, with a code.
      if (isChatProblem(result.error)) {
        throw new ChatProblemError(result.response.status, result.error);
      }
      return unwrap(result);
    },
    ...usePlanChangeHandlers(),
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
