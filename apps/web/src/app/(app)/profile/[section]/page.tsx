import { cn } from "cn";
import { ArrowLeftIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { AccountControls } from "@/components/profile/account-controls";
import { AllergiesForm } from "@/components/profile/allergies-form";
import { BodyForm } from "@/components/profile/body-form";
import { CalendarForm } from "@/components/profile/calendar-form";
import { GoalsForm } from "@/components/profile/goals-form";
import { MealsForm } from "@/components/profile/meals-form";
import { PreferencesForm } from "@/components/profile/preferences-form";
import { QuickNightsForm } from "@/components/profile/quick-nights-form";
import { RegionForm } from "@/components/profile/region-form";
import { RemindersForm } from "@/components/profile/reminders-form";
import { SECTIONS, type SectionId, sectionById } from "@/components/profile/sections";
import { TemplatesForm } from "@/components/profile/templates-form";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";

const BODY: Record<SectionId, ReactNode> = {
  goals: <GoalsForm />,
  allergies: <AllergiesForm />,
  preferences: <PreferencesForm />,
  meals: <MealsForm />,
  "busy-nights": <QuickNightsForm />,
  body: <BodyForm />,
  templates: <TemplatesForm />,
  calendar: <CalendarForm />,
  reminders: <RemindersForm />,
  region: <RegionForm />,
  appearance: <ThemeToggle />,
  account: <AccountControls />,
};

// Every section is prerendered; any other name is a 404 (below).
export function generateStaticParams() {
  return SECTIONS.map((s) => ({ section: s.id }));
}

export async function generateMetadata({
  params,
}: PageProps<"/profile/[section]">): Promise<Metadata> {
  const { section } = await params;
  return { title: sectionById(section)?.title ?? "Profile" };
}

export default async function ProfileSectionPage({ params }: PageProps<"/profile/[section]">) {
  const { section } = await params;
  const found = sectionById(section);
  if (!found) notFound();
  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/profile"
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2 self-start")}
      >
        <ArrowLeftIcon aria-hidden />
        Profile
      </Link>
      <h1 className="text-3xl font-semibold">{found.title}</h1>
      {BODY[found.id]}
    </div>
  );
}
