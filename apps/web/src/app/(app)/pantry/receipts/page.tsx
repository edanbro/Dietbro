import type { Metadata } from "next";
import { Suspense } from "react";

import { ReceiptIntake } from "@/components/pantry/receipt-intake";

export const metadata: Metadata = { title: "Add from receipt" };

export default function Page() {
  // The intake reads ?tab= (useSearchParams), so it renders inside Suspense.
  return (
    <Suspense>
      <ReceiptIntake />
    </Suspense>
  );
}
