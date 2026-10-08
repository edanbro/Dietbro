import type { Metadata } from "next";

import { SetupWizard } from "@/components/setup-wizard";

export const metadata: Metadata = { title: "Set up · Larder" };

export default function SetupPage() {
  return <SetupWizard />;
}
