"use client";

import { cn } from "cn";
import {
  ArrowLeftIcon,
  BanIcon,
  ChefHatIcon,
  ExternalLinkIcon,
  HeartIcon,
  PencilIcon,
  TriangleAlertIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { GradeBadge } from "@/components/food-bits";
import { ErrorAlert } from "@/components/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/browser";
import { type Recipe, useAllergens, useRecipe, useRecipeFeedback } from "@/lib/api/hooks";
import { parseServings, scaledAmount, scaleFactor, steps } from "@/lib/cooking";
import { allergenLabel, formatMinutes, formatNumber, humanize } from "@/lib/format";
import { APP_NAME } from "@/lib/brand";
import { MoreNutrients } from "@/components/plan/macro-bars";
import { AddToList } from "@/components/recipe/add-to-list";
import { RecipeArt } from "@/components/recipe/recipe-art";
import { Micronutrients } from "@/components/nutrients/micronutrients";
import { RecipeNotes } from "@/components/recipe/recipe-notes";
import { ShareLinkButton } from "@/components/share-link-button";

/** http(s) URLs only: recipe data comes from third parties. */
export function safeUrl(url: string | null): URL | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed : null;
  } catch {
    return null;
  }
}

function BackButton() {
  const router = useRouter();
  return (
    <Button
      variant="ghost"
      size="sm"
      className="-ml-2 self-start"
      onClick={() => (window.history.length > 1 ? router.back() : router.push("/plan"))}
    >
      <ArrowLeftIcon aria-hidden />
      Back
    </Button>
  );
}

function Nutrition({ recipe }: { recipe: Recipe }) {
  const n = recipe.per_serving;
  if (!n) {
    return (
      <p className="text-sm text-muted-foreground">
        Nutrition isn&apos;t available for this recipe.
      </p>
    );
  }
  const cells = [
    { label: "Calories", value: `${formatNumber(n.kcal)} kcal` },
    { label: "Protein", value: `${formatNumber(n.protein_g)} g` },
    { label: "Carbs", value: `${formatNumber(n.carbs_g)} g` },
    { label: "Fat", value: `${formatNumber(n.fat_g)} g` },
  ];
  return (
    <div className="flex flex-col gap-2">
      <dl className="grid grid-cols-4 gap-2">
        {cells.map((c) => (
          <div key={c.label} className="flex flex-col items-center rounded-lg bg-muted/60 px-1 py-2">
            <dt className="text-xs text-muted-foreground">{c.label}</dt>
            <dd className="text-sm font-semibold tabular-nums">{c.value}</dd>
          </div>
        ))}
      </dl>
      <MoreNutrients values={n} />
    </div>
  );
}

function Allergens({ recipe }: { recipe: Recipe }) {
  const { data: options } = useAllergens();
  return (
    <section aria-labelledby="recipe-allergens" className="flex flex-col gap-2">
      <h2 id="recipe-allergens" className="text-base font-semibold">
        Allergens
      </h2>
      {recipe.allergens.length ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Contains">
          {recipe.allergens.map((a) => (
            <li key={a}>
              <Badge variant="outline">{allergenLabel(a, options)}</Badge>
            </li>
          ))}
        </ul>
      ) : recipe.allergens_complete ? (
        <p className="text-sm text-muted-foreground">None of the 14 major allergens found.</p>
      ) : null}
      {recipe.allergens_complete ? null : (
        <p className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
          <TriangleAlertIcon aria-hidden className="mt-0.5 size-3 shrink-0" />
          May be incomplete: some ingredients couldn&apos;t be matched to a known food.
        </p>
      )}
      {recipe.suitable_for.length ? (
        <p className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">Suitable for:</span>
          {recipe.suitable_for.map((d) => (
            <Badge key={d} variant="secondary">
              {humanize(d)}
            </Badge>
          ))}
        </p>
      ) : null}
    </section>
  );
}

/** Favourite (planned more often) or never again; pressing the active one clears it. */
function Feedback({ recipe }: { recipe: Recipe }) {
  const save = useRecipeFeedback(recipe.id);
  const verdict = recipe.feedback ?? null;
  const set = (next: "favourite" | "never") =>
    save.mutate(verdict === next ? null : next, {
      onSuccess: () =>
        toast.success(
          verdict === next
            ? "Cleared"
            : next === "favourite"
              ? "Saved to favourites: planned more often"
              : "We won't plan this again",
        ),
      onError: (e) =>
        toast.error(e instanceof ApiError && e.messages[0] ? e.messages[0] : "Couldn't save that"),
    });
  return (
    <div className="flex flex-wrap gap-2">
      <Button
        variant="outline"
        size="sm"
        aria-pressed={verdict === "favourite"}
        disabled={save.isPending}
        onClick={() => set("favourite")}
      >
        <HeartIcon
          aria-hidden
          className={cn(verdict === "favourite" && "fill-red-500 text-red-500")}
        />
        {verdict === "favourite" ? "Favourite" : "Add to favourites"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        aria-pressed={verdict === "never"}
        disabled={save.isPending}
        onClick={() => set("never")}
      >
        <BanIcon aria-hidden className={cn(verdict === "never" && "text-destructive")} />
        {verdict === "never" ? "Never planned" : "Never again"}
      </Button>
      <ShareLinkButton target={{ kind: "recipe", recipe_id: recipe.id }} title={recipe.name} />
      {/* Your own recipe changes in place; a catalogue one is saved as your copy. */}
      <Link
        href={`/recipes/${recipe.id}/edit`}
        className={buttonVariants({ variant: "outline", size: "sm" })}
      >
        <PencilIcon aria-hidden />
        {recipe.generated ? "Edit" : "Edit a copy"}
      </Link>
    </div>
  );
}

function Credit({ recipe }: { recipe: Recipe }) {
  const original = safeUrl(recipe.source_url);
  const link = original ? (
    <a
      href={original.href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 underline underline-offset-3"
    >
      {original.hostname.replace(/^www\./, "")}
      <ExternalLinkIcon aria-hidden className="size-3" />
    </a>
  ) : null;
  return (
    <footer className="flex flex-col gap-1 border-t pt-3 text-xs text-muted-foreground">
      {recipe.source === "mealdb" ? (
        <p>
          {recipe.image_url ? "Recipe and photo" : "Recipe"} from{" "}
          <a
            href="https://www.themealdb.com"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-3"
          >
            TheMealDB
          </a>
          .
        </p>
      ) : recipe.source === "curated" ? (
        <p>A {APP_NAME} recipe.</p>
      ) : (
        <p>Source: {recipe.source}</p>
      )}
      {link ? <p>Original recipe: {link}</p> : null}
    </footer>
  );
}

/** A recipe: photo, numbers per serving, allergens and diets, ingredients and method. */
export function RecipePage({ id }: { id: number }) {
  const { data: recipe, isPending, error, refetch } = useRecipe(id);
  const servings = parseServings(useSearchParams().get("servings"));

  if (isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy>
        <Skeleton className="aspect-video w-full rounded-xl" />
        <Skeleton className="h-8 w-3/4" />
        <Skeleton className="h-16" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <BackButton />
        {error instanceof ApiError && error.status === 404 ? (
          <p className="text-sm text-muted-foreground">We couldn&apos;t find that recipe.</p>
        ) : (
          <ErrorAlert error={error} onRetry={() => void refetch()} />
        )}
        <Link href="/plan" className={cn(buttonVariants({ variant: "outline" }))}>
          Go to your plan
        </Link>
      </div>
    );
  }

  const factor = servings ? scaleFactor(servings, recipe.servings) : 1;
  const details = [
    recipe.minutes ? `About ${formatMinutes(recipe.minutes)}` : null,
    recipe.cuisine,
    recipe.servings
      ? `Serves ${recipe.servings}${recipe.servings_estimated ? " (estimated)" : ""}`
      : null,
  ].filter(Boolean);

  return (
    <article className="flex flex-col gap-5">
      <BackButton />
      <RecipeArt
        recipe={recipe}
        alt={recipe.image_url ? recipe.name : ""}
        eager
        className={cn("w-full rounded-xl", recipe.image_url ? "aspect-video" : "aspect-[3/1]")}
      />
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{recipe.name}</h1>
        {details.length ? (
          <p className="text-sm text-muted-foreground">{details.join(" · ")}</p>
        ) : null}
        <GradeBadge grade={recipe.grade} className="mt-1" />
      </header>
      <Link
        href={`/recipes/${recipe.id}/cook${servings ? `?servings=${servings}` : ""}`}
        className={cn(buttonVariants({ size: "lg" }), "w-full")}
      >
        <ChefHatIcon aria-hidden />
        Start cooking{servings ? ` (${servings} ${servings === 1 ? "serving" : "servings"})` : ""}
      </Link>
      <Feedback recipe={recipe} />
      <RecipeNotes key={recipe.note?.updated_at ?? "none"} recipe={recipe} />

      <section aria-labelledby="recipe-nutrition" className="flex flex-col gap-2">
        <h2 id="recipe-nutrition" className="text-base font-semibold">
          Per serving
        </h2>
        <Nutrition recipe={recipe} />
      </section>

      {recipe.per_serving ? (
        <section aria-labelledby="recipe-micros" className="flex flex-col gap-2">
          <h2 id="recipe-micros" className="text-base font-semibold">
            Vitamins and minerals
          </h2>
          <Micronutrients values={recipe.per_serving} mode="serving" />
        </section>
      ) : null}

      <Allergens recipe={recipe} />

      <section aria-labelledby="recipe-ingredients" className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="recipe-ingredients" className="text-base font-semibold">
            Ingredients
          </h2>
          <AddToList recipe={recipe} servings={servings} />
        </div>
        {factor !== 1 ? (
          <p className="text-xs text-muted-foreground">
            For {servings} {servings === 1 ? "serving" : "servings"}, as planned (the recipe
            makes {recipe.servings}).
          </p>
        ) : null}
        <ul className="flex flex-col divide-y rounded-lg border text-sm">
          {recipe.ingredients.map((ing, i) => (
            <li key={`${ing.name}-${i}`} className="flex gap-3 px-3 py-2">
              <span className="w-24 shrink-0 text-muted-foreground tabular-nums">
                {scaledAmount(ing, factor)}
              </span>
              <span className="min-w-0 flex-1">{ing.name}</span>
              {ing.in_pantry ? (
                <span className="shrink-0 text-xs text-emerald-700 dark:text-emerald-400">
                  In your pantry
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="recipe-method" className="flex flex-col gap-2">
        <h2 id="recipe-method" className="text-base font-semibold">
          Method
        </h2>
        <div className="flex flex-col gap-3 text-sm leading-relaxed">
          {steps(recipe.instructions).map((s, i) => (
            <p key={i}>{s}</p>
          ))}
        </div>
      </section>

      <Credit recipe={recipe} />
    </article>
  );
}
