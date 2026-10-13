import { auth } from "@clerk/nextjs/server";
import {
  CalendarDaysIcon,
  MessageCircleIcon,
  RefrigeratorIcon,
  ScanBarcodeIcon,
} from "lucide-react";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { HomeActions } from "@/components/home-actions";
import { APP_NAME } from "@/lib/brand";

const FEATURES = [
  {
    icon: RefrigeratorIcon,
    title: "Starts from your kitchen",
    text: "Plans a week of meals around what you already have, using up what expires first.",
  },
  {
    icon: CalendarDaysIcon,
    title: "Your goals, your rules",
    text: "Calories, protein, budget, allergies and diet: every plan is checked against them.",
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
];

/** Signed-in visitors go straight to their plan. */
async function SignedInRedirect() {
  const { userId } = await auth();
  if (userId) redirect("/plan");
  return null;
}

export default function Home() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-8 px-6 py-16">
      <Suspense>
        <SignedInRedirect />
      </Suspense>
      <div className="flex flex-col gap-3">
        <h1 className="text-4xl font-semibold tracking-tight">{APP_NAME}</h1>
        <p className="text-lg text-muted-foreground">
          Plans your week around what&apos;s already in your kitchen, and re-plans when life
          happens.
        </p>
      </div>
      <HomeActions />
      <ul className="flex flex-col gap-4">
        {FEATURES.map(({ icon: Icon, title, text }) => (
          <li key={title} className="flex gap-3">
            <Icon className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden />
            <div>
              <p className="font-medium">{title}</p>
              <p className="text-sm text-muted-foreground">{text}</p>
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
