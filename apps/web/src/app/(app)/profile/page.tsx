import type { Metadata } from "next";
import Link from "next/link";

import { AccountControls } from "@/components/profile/account-controls";
import { AllergiesForm } from "@/components/profile/allergies-form";
import { BodyForm } from "@/components/profile/body-form";
import { GoalsForm } from "@/components/profile/goals-form";
import { PreferencesForm } from "@/components/profile/preferences-form";
import { RegionForm } from "@/components/profile/region-form";
import { ThemeToggle } from "@/components/theme-toggle";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = { title: "Profile" };

const SECTIONS = [
  { id: "goals", title: "Goals", body: <GoalsForm /> },
  { id: "allergies", title: "Allergies", body: <AllergiesForm /> },
  { id: "preferences", title: "Preferences", body: <PreferencesForm /> },
  { id: "body", title: "Body stats", body: <BodyForm /> },
  { id: "region", title: "Region", body: <RegionForm /> },
  { id: "appearance", title: "Appearance", body: <ThemeToggle /> },
  { id: "account", title: "Your data", body: <AccountControls /> },
];

export default function ProfilePage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>
      {SECTIONS.map((s) => (
        <Card key={s.id} id={s.id}>
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
