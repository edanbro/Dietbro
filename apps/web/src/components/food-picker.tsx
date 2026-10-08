"use client";

import { SearchIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";
import { type FoodSummary, useFoodSearch } from "@/lib/api/hooks";

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

/** Type-ahead over USDA foods; curated ingredient names rank first. */
export function FoodPicker({
  onPick,
  placeholder = "Search foods, e.g. onion",
  id = "food-search",
}: {
  onPick: (food: FoodSummary) => void;
  placeholder?: string;
  id?: string;
}) {
  const [q, setQ] = useState("");
  const query = useDebounced(q, 250);
  const { data, isFetching } = useFoodSearch(query);

  return (
    <div className="flex flex-col gap-2">
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          id={id}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={placeholder}
          className="pl-8"
          autoComplete="off"
          aria-label={placeholder}
        />
      </div>
      {query.trim().length >= 2 ? (
        <ul className="flex max-h-64 flex-col overflow-y-auto rounded-lg border" aria-busy={isFetching}>
          {(data ?? []).map((food) => (
            <li key={food.id}>
              <button
                type="button"
                className="flex w-full flex-col items-start gap-0.5 border-b px-3 py-2.5 text-left last:border-b-0 hover:bg-muted"
                onClick={() => {
                  onPick(food);
                  setQ("");
                }}
              >
                <span className="text-sm">{food.description}</span>
                <span className="text-xs text-muted-foreground">
                  {food.category ?? "Food"}
                  {food.kcal !== null && food.kcal !== undefined
                    ? ` · ${Math.round(food.kcal)} kcal/100 g`
                    : ""}
                </span>
              </button>
            </li>
          ))}
          {data && data.length === 0 ? (
            <li className="px-3 py-2.5 text-sm text-muted-foreground">No matches</li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}
