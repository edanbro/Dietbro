import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache, Suspense } from "react";

import { Logo } from "@/components/logo";
import { SLOT_LABEL } from "@/components/plan/slots";
import { RecipeArt } from "@/components/recipe/recipe-art";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { createApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { APP_NAME } from "@/lib/brand";
import { longDate } from "@/lib/dates";
import { formatNumber } from "@/lib/format";

type Shared = components["schemas"]["SharedOut"];
type Recipe = components["schemas"]["RecipeDetail"];
type Day = components["schemas"]["SharedDayOut"];

/** One fetch per request, shared by the metadata and the page. */
const load = cache(async (token: string): Promise<Shared | null> => {
  const { data, response } = await createApiClient().GET("/public/share/{token}", {
    params: { path: { token } },
    signal: AbortSignal.timeout(5000),
  });
  if (response.status === 404 || !data) return null;
  return data;
});

export async function generateMetadata({ params }: PageProps<"/s/[token]">): Promise<Metadata> {
  const shared = await load((await params).token);
  if (!shared) return { title: "Link not found", robots: { index: false } };
  const title = shared.recipe ? shared.recipe.name : "A week of meals";
  const description = shared.recipe
    ? `A recipe shared from ${APP_NAME}.`
    : `Seven days of breakfasts, lunches and dinners, planned with ${APP_NAME}.`;
  const image = shared.recipe?.image_url;
  return {
    title,
    description,
    robots: { index: false },
    openGraph: { title, description, ...(image ? { images: [image] } : {}) },
  };
}

function SharedRecipe({ recipe }: { recipe: Recipe }) {
  const per = recipe.per_serving;
  const details = [
    recipe.cuisine,
    recipe.servings ? `Serves ${recipe.servings}` : null,
    per ? `${formatNumber(per.kcal)} kcal a serving` : null,
  ].filter(Boolean);
  return (
    <article className="flex flex-col gap-6">
      <RecipeArt
        recipe={recipe}
        alt={recipe.image_url ? recipe.name : ""}
        eager
        className={recipe.image_url ? "aspect-video w-full rounded-2xl" : "aspect-[3/1] w-full rounded-2xl"}
      />
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold text-balance">{recipe.name}</h1>
        {details.length ? (
          <p className="text-muted-foreground">{details.join(" · ")}</p>
        ) : null}
        {recipe.allergens.length ? (
          <p className="text-sm text-muted-foreground">
            Contains: {recipe.allergens.map((a) => a.replaceAll("_", " ")).join(", ")}
          </p>
        ) : null}
      </header>
      <section aria-labelledby="ingredients" className="flex flex-col gap-2">
        <h2 id="ingredients" className="text-xl font-semibold">
          Ingredients
        </h2>
        <ul className="flex flex-col divide-y rounded-xl border bg-card">
          {recipe.ingredients.map((i, n) => (
            <li key={`${i.name}-${n}`} className="flex gap-4 px-4 py-2.5 text-sm">
              <span className="w-24 shrink-0 text-muted-foreground">{i.measure}</span>
              <span>{i.name}</span>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="method" className="flex flex-col gap-2">
        <h2 id="method" className="text-xl font-semibold">
          Method
        </h2>
        <div className="flex flex-col gap-3 leading-relaxed">
          {recipe.instructions
            .split(/\n\s*\n|\r\n\s*\r\n/)
            .filter((p) => p.trim())
            .map((p, n) => (
              <p key={n}>{p.trim()}</p>
            ))}
        </div>
      </section>
      {recipe.source_url ? (
        <p className="text-sm text-muted-foreground">
          Originally from{" "}
          <a href={recipe.source_url} className="underline underline-offset-4" rel="nofollow">
            {new URL(recipe.source_url).hostname.replace(/^www\./, "")}
          </a>
          .
        </p>
      ) : null}
    </article>
  );
}

function SharedWeek({ days }: { days: Day[] }) {
  return (
    <article className="flex flex-col gap-6">
      <h1 className="text-3xl font-semibold">A week of meals</h1>
      {days.map((day) => (
        <section key={day.date} aria-label={longDate(day.date)} className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">{longDate(day.date)}</h2>
          <ul className="flex flex-col gap-2">
            {day.meals.map((m) => (
              <li key={m.slot} className="flex items-center gap-3 rounded-xl border bg-card p-2.5">
                <RecipeArt recipe={m.recipe} className="size-14 shrink-0 rounded-lg" />
                <div className="flex min-w-0 flex-col">
                  <span className="text-xs text-muted-foreground">{SLOT_LABEL[m.slot]}</span>
                  <span className="truncate font-medium">{m.recipe.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {formatNumber(m.kcal)} kcal
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </article>
  );
}

async function Shared({ params }: { params: PageProps<"/s/[token]">["params"] }) {
  const shared = await load((await params).token);
  if (!shared) notFound();
  return (
    <>
      {shared.recipe ? <SharedRecipe recipe={shared.recipe} /> : null}
      {shared.days ? <SharedWeek days={shared.days} /> : null}
    </>
  );
}

/** A read-only page for a share link: anyone with the link, no sign-in. */
export default function SharedPage({ params }: PageProps<"/s/[token]">) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col gap-8 px-4 py-8">
      <Link href="/" aria-label={`${APP_NAME} home`} className="self-start">
        <Logo />
      </Link>
      {/* The token is request-time data, so it's read inside Suspense. */}
      <Suspense
        fallback={
          <div className="flex flex-col gap-4" aria-busy>
            <Skeleton className="aspect-video w-full rounded-2xl" />
            <Skeleton className="h-9 w-3/4" />
            <Skeleton className="h-40" />
          </div>
        }
      >
        <Shared params={params} />
      </Suspense>
      <aside className="flex flex-col items-start gap-3 rounded-2xl bg-secondary p-5">
        <p className="font-heading text-xl font-semibold">Plan your own week</p>
        <p className="text-sm text-muted-foreground">
          {APP_NAME} plans breakfast, lunch and dinner around your goals, your allergies and
          what&apos;s already in your kitchen.
        </p>
        <Link href="/" className={buttonVariants()}>
          Try {APP_NAME}
        </Link>
      </aside>
    </main>
  );
}
