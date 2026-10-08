import type { Metadata } from "next";

import { PantryPage } from "@/components/pantry/pantry-page";

export const metadata: Metadata = { title: "Pantry · Larder" };

export default function Page() {
  return <PantryPage />;
}
