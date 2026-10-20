import type { Metadata } from "next";
import Link from "next/link";

import { AccountControls } from "@/components/profile/account-controls";
import { AllergiesForm } from "@/components/profile/allergies-form";
import { BodyForm } from "@/components/profile/body-form";
import { CalendarForm } from "@/components/profile/calendar-form";
import { GoalsForm } from "@/components/profile/goals-form";
import { PreferencesForm } from "@/components/profile/preferences-form";
import { RegionForm } from "@/components/profile/region-form";
import { RemindersForm } from "@/components/profile/reminders-form";
import { ThemeToggle } from "@/components/theme-toggle";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = { title: "Profile" };

const SECTIONS = [
  { id: "goals", title: "Goals", body: <GoalsForm /> },
  { id: "allergies", title: "Allergies", body: <AllergiesForm /> },
  { id: "preferences", title: "Preferences", body: <PreferencesForm /> },
  { id: "body", title: "Body stats", body: <BodyForm /> },
  { id: "region", title: "Region", body: <RegionForm /> },
  { id: "reminders", title: "Reminders", body: <RemindersForm /> },
  { id: "calendar", title: "Calendar", body: <CalendarForm /> },
  { id: "appearance", title: "Appearance", body: <ThemeToggle /> },
  { id: "account", title: "Your data", body: <AccountControls /> },
];

export default function ProfilePage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-3xl font-semibold">Profile</h1>
      {/* A long page: jump straight to a section. */}
      <nav aria-label="Profile sections" className="-mx-4 overflow-x-auto px-4 pb-1">
        <ul className="flex w-max gap-2">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                className="inline-flex h-9 items-center rounded-full border bg-card px-3.5 text-sm hover:bg-muted"
              >
                {s.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      {SECTIONS.map((s) => (
        <Card key={s.id} id={s.id} className="scroll-mt-20">
          <CardHeader>
            <CardTitle>{s.title}</CardTitle>
          </CardHeader>
          <CardContent>{s.body}</CardContent>
        </Card>
      ))}
      <Link
        href="/attributions"
        className="text-center text-xs text-muted-foreground underline-offset-4 hover:underline"
      >
        Data sources and licences
      </Link>
    </div>
  );
}
