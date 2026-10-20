"use client";

import { cn } from "cn";
import { HeartIcon, SearchIcon, UtensilsIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useDebounced } from "@/components/food-picker";
import { ErrorAlert } from "@/components/form-bits";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/browser";
import { type RecipeListItem, type Slot, useRecipeList } from "@/lib/api/hooks";
import { formatNumber } from "@/lib/format";
import { EmptyState } from "@/components/empty-state";

const SLOTS: { value: Slot | null; label: string }[] = [
  { value: null, label: "All" },
  { value: "breakfast", label: "Breakfast" },
  { value: "lunch", label: "Lunch" },
  { value: "dinner", label: "Dinner" },
  { value: "snack", label: "Snacks" },
];

function Chip({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors",
        pressed ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

function RecipeTile({ recipe }: { recipe: RecipeListItem }) {
  return (
    <li>
      <Link
        href={`/recipes/${recipe.id}`}
        className="flex h-full flex-col overflow-hidden rounded-xl border transition-colors hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <div className="relative aspect-[4/3] bg-muted">
          {recipe.image_url ? (
            // Third-party photo of unknown size; see MealCard.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={recipe.image_url}
              alt=""
              loading="lazy"
              decoding="async"
              className="size-full object-cover"
            />
          ) : (
            <div className="grid size-full place-items-center text-muted-foreground">
              <UtensilsIcon aria-hidden className="size-8" />
            </div>
          )}
          {recipe.favourite ? (
            <span className="absolute top-2 right-2 grid size-7 place-items-center rounded-full bg-background/90">
              <HeartIcon aria-label="Favourite" className="size-4 fill-red-500 text-red-500" />
            </span>
          ) : null}
        </div>
        <div className="flex flex-1 flex-col gap-0.5 p-2.5">
          <span className="line-clamp-2 text-sm font-medium">{recipe.name}</span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {formatNumber(recipe.kcal_per_serving)} kcal ·{" "}
            {formatNumber(recipe.protein_g_per_serving)} g protein
          </span>
          {recipe.uses_pantry.length ? (
            <span className="line-clamp-1 text-xs text-emerald-700 dark:text-emerald-400">
              Uses your {recipe.uses_pantry.slice(0, 2).join(", ").toLowerCase()}
            </span>
          ) : recipe.cuisine ? (
            <span className="text-xs text-muted-foreground">{recipe.cuisine}</span>
          ) : null}
        </div>
      </Link>
    </li>
  );
}

/** Every recipe safe for the user: search, filter by meal and favourites, more on demand. */
export function RecipeBrowser() {
  const [q, setQ] = useState("");
  const [slot, setSlot] = useState<Slot | null>(null);
  const [favourites, setFavourites] = useState(false);
  const query = { q: useDebounced(q.trim(), 300), slot, favourites };
  const list = useRecipeList(query);
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total ?? 0;
  const setupNeeded = list.error instanceof ApiError && list.error.status === 409;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Recipes</h1>
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search, e.g. spicy chicken"
          className="pl-8"
          aria-label="Search recipes"
          autoComplete="off"
        />
      </div>
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1" role="group" aria-label="Filters">
        <Chip pressed={favourites} onClick={() => setFavourites(!favourites)}>
          <HeartIcon aria-hidden className={cn("size-4", favourites && "fill-current")} />
          Favourites
        </Chip>
        {SLOTS.map((s) => (
          <Chip key={s.label} pressed={slot === s.value} onClick={() => setSlot(s.value)}>
            {s.label}
          </Chip>
        ))}
      </div>

      {setupNeeded ? (
        <div className="flex flex-col items-start gap-2 rounded-lg border p-4 text-sm">
          <p>Tell us about your allergies and diet first, so we only show recipes safe for you.</p>
          <Link href="/setup" className={buttonVariants({ size: "sm" })}>
            Set up
          </Link>
        </div>
      ) : list.error ? (
        <ErrorAlert error={list.error} onRetry={() => void list.refetch()} />
      ) : list.isPending ? (
        <ul className="grid grid-cols-2 gap-3" aria-busy>
          {Array.from({ length: 6 }, (_, i) => (
            <li key={i}>
              <Skeleton className="aspect-[4/5] rounded-xl" />
            </li>
          ))}
        </ul>
      ) : items.length ? (
        <>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {formatNumber(total)} {total === 1 ? "recipe" : "recipes"} safe for you
          </p>
          <ul className="grid grid-cols-2 gap-3">
            {items.map((r) => (
              <RecipeTile key={r.id} recipe={r} />
            ))}
          </ul>
          {list.hasNextPage ? (
            <Button
              variant="outline"
              disabled={list.isFetchingNextPage}
              onClick={() => void list.fetchNextPage()}
            >
              {list.isFetchingNextPage ? "Loading…" : "More recipes"}
            </Button>
          ) : null}
        </>
      ) : (
        <div aria-live="polite">
          {favourites ? (
            <EmptyState art="search" title="No favourites yet">
              Tap the heart on a recipe you love and the planner will pick it more often.
            </EmptyState>
          ) : (
            <EmptyState art="search" title="Nothing matches">
              No safe recipe matches that. Try other words.
            </EmptyState>
          )}
        </div>
      )}
    </div>
  );
}
