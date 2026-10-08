import type { Metadata } from "next";

import { AccountControls } from "@/components/profile/account-controls";
import { AllergiesForm } from "@/components/profile/allergies-form";
import { BodyForm } from "@/components/profile/body-form";
import { GoalsForm } from "@/components/profile/goals-form";
import { PreferencesForm } from "@/components/profile/preferences-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = { title: "Profile · Larder" };

const SECTIONS = [
  { id: "goals", title: "Goals", body: <GoalsForm /> },
  { id: "allergies", title: "Allergies", body: <AllergiesForm /> },
  { id: "preferences", title: "Preferences", body: <PreferencesForm /> },
  { id: "body", title: "Body stats", body: <BodyForm /> },
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
    </div>
  );
}
