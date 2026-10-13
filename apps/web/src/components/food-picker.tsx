"use client";

import { SearchIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { ProductThumb } from "@/components/food-bits";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { type FoodScope, type FoodSummary, useFoodSearch } from "@/lib/api/hooks";

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

/**
 * Type-ahead over foods (generic foods first, then packaged products sold where the user lives);
 * curated ingredient names rank first. `scope="generic"` leaves products out (allergies and
 * preferences are about foods, not brands).
 */
export function FoodPicker({
  onPick,
  placeholder = "Search foods, e.g. onion",
  id = "food-search",
  scope = "all",
}: {
  onPick: (food: FoodSummary) => void;
  placeholder?: string;
  id?: string;
  scope?: FoodScope;
}) {
  const [q, setQ] = useState("");
  const query = useDebounced(q, 250);
  const search = useFoodSearch(query, scope);
  const data = search.data?.pages.flat();

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
        <ul
          className="flex max-h-72 flex-col overflow-y-auto rounded-lg border"
          aria-busy={search.isFetching}
        >
          {(data ?? []).map((food) => (
            <li key={food.id}>
              <button
                type="button"
                className="flex w-full items-center gap-3 border-b px-3 py-2.5 text-left last:border-b-0 hover:bg-muted"
                onClick={() => {
                  onPick(food);
                  setQ("");
                }}
              >
                <ProductThumb url={food.image_url} />
                <span className="flex min-w-0 flex-1 flex-col items-start gap-0.5">
                  <span className="flex w-full items-start justify-between gap-2 text-sm">
                    <span>
                      {food.brand ? <span className="font-medium">{food.brand} </span> : null}
                      {food.description}
                    </span>
                    {food.kind === "product" ? (
                      <Badge variant="secondary" className="shrink-0">
                        Product
                      </Badge>
                    ) : null}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {food.category ?? (food.kind === "product" ? "Packaged food" : "Food")}
                    {food.kcal !== null && food.kcal !== undefined
                      ? ` · ${Math.round(food.kcal)} kcal/100 g`
                      : ""}
                  </span>
                </span>
              </button>
            </li>
          ))}
          {data && data.length === 0 ? (
            <li className="px-3 py-2.5 text-sm text-muted-foreground">No matches</li>
          ) : null}
          {search.hasNextPage ? (
            <li>
              <button
                type="button"
                className="w-full px-3 py-2.5 text-left text-sm font-medium text-primary hover:bg-muted disabled:opacity-50"
                disabled={search.isFetchingNextPage}
                onClick={() => void search.fetchNextPage()}
              >
                {search.isFetchingNextPage ? "Loading…" : "More results"}
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}
