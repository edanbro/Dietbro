import { auth } from "@clerk/nextjs/server";
import {
  CalendarDaysIcon,
  ChefHatIcon,
  MessageCircleIcon,
  RefrigeratorIcon,
  ScanBarcodeIcon,
  ShieldCheckIcon,
} from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { HomeActions } from "@/components/home-actions";
import { APP_NAME } from "@/lib/brand";
import { Logo } from "@/components/logo";

const FEATURES = [
  {
    icon: RefrigeratorIcon,
    title: "Starts from your kitchen",
    text: "Plans a week of meals around what you already have, using up what expires first.",
  },
  {
    icon: ShieldCheckIcon,
    title: "Allergies are hard rules",
    text: "Every plan is checked against your allergies and diet before you see it. Always.",
  },
  {
    icon: CalendarDaysIcon,
    title: "Your goals, your budget",
    text: "Calories, protein, fat, carbs and a weekly budget, priced from your own receipts.",
  },
  {
    icon: MessageCircleIcon,
    title: "Re-plans when life happens",
    text: "Skipped dinner or had pizza for lunch? Say so and the rest of the week adjusts.",
  },
  {
    icon: ScanBarcodeIcon,
    title: "Quick to stock",
    text: "Scan barcodes, paste a receipt, or search 200,000+ foods sold in Ireland and the UK.",
  },
  {
    icon: ChefHatIcon,
    title: "Cook it step by step",
    text: "Amounts scaled to your servings, timers from the method, and the screen stays on.",
  },
];

/** A sample of what a planned day looks like (static, for the landing page). */
const SAMPLE = [
  { slot: "Breakfast", name: "Porridge with berries", kcal: 420 },
  { slot: "Lunch", name: "Chicken and broccoli rice", kcal: 610 },
  { slot: "Dinner", name: "Irish stew", kcal: 680 },
];

/** Signed-in visitors go straight to their plan. */
async function SignedInRedirect() {
  const { userId } = await auth();
  if (userId) redirect("/plan");
  return null;
}

export default function Home() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-5xl flex-col gap-14 px-6 py-12 lg:py-20">
      <Suspense>
        <SignedInRedirect />
      </Suspense>
      <Logo size="lg" />

      <section className="grid items-center gap-10 lg:grid-cols-[1.1fr_1fr]">
        <div className="flex flex-col gap-6">
          <h1 className="text-4xl font-semibold tracking-tight text-balance lg:text-5xl">
            A week of meals, planned around{" "}
            <span className="text-primary">what&apos;s already in your kitchen</span>.
          </h1>
          <p className="text-lg text-pretty text-muted-foreground">
            {APP_NAME} plans breakfast, lunch and dinner for your goals and allergies, builds the
            shopping list, and re-plans when life happens.
          </p>
          <div className="max-w-sm">
            <HomeActions />
          </div>
        </div>
        <figure
          aria-label="An example planned day"
          className="rounded-2xl border bg-card p-4 shadow-sm motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-2 motion-safe:duration-500"
        >
          <figcaption className="mb-3 flex items-baseline justify-between text-sm">
            <span className="font-medium">Today</span>
            <span className="text-muted-foreground tabular-nums">1,710 kcal · 98 g protein</span>
          </figcaption>
          <ul className="flex flex-col gap-2">
            {SAMPLE.map((m) => (
              <li key={m.slot} className="flex items-center gap-3 rounded-xl border p-3">
                <span className="grid size-10 place-items-center rounded-lg bg-accent text-accent-foreground">
                  <ChefHatIcon aria-hidden className="size-5" />
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="text-xs text-muted-foreground">{m.slot}</span>
                  <span className="truncate font-medium">{m.name}</span>
                </span>
                <span className="text-sm text-muted-foreground tabular-nums">{m.kcal} kcal</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-emerald-700 dark:text-emerald-400">
            Uses your oats, chicken and potatoes before they go off.
          </p>
        </figure>
      </section>

      <section aria-labelledby="features">
        <h2 id="features" className="sr-only">
          What it does
        </h2>
        <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <li key={title} className="flex gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary text-secondary-foreground">
                <Icon className="size-4" aria-hidden />
              </span>
              <div>
                <p className="font-medium">{title}</p>
                <p className="text-sm text-muted-foreground">{text}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <footer className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-6 text-xs text-muted-foreground">
        <span>Not medical advice. Check labels for allergens.</span>
        <Link href="/attributions" className="underline-offset-4 hover:underline">
          Data sources and licences
        </Link>
      </footer>
    </main>
  );
}
