"use client";

import { ReceiptTextIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { BarcodeScan } from "@/components/pantry/barcode-scan";
import { ExpiryAlerts } from "@/components/pantry/expiry-alerts";
import { PantryAdd } from "@/components/pantry/pantry-add";
import { PantryList } from "@/components/pantry/pantry-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type FoodSummary, useMe } from "@/lib/api/hooks";
import { APP_NAME } from "@/lib/brand";

export function PantryPage() {
  const { data: me } = useMe();
  const [scanned, setScanned] = useState<FoodSummary | null>(null);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Pantry</h1>
        <Link href="/pantry/receipts" className={buttonVariants({ variant: "outline" })}>
          <ReceiptTextIcon aria-hidden />
          Add from receipt
        </Link>
      </div>
      {me && !me.setup_complete ? (
        <Alert>
          <AlertDescription className="flex items-center justify-between gap-2">
            Finish setting up so {APP_NAME} can plan for you.
            <Link href="/setup" className={buttonVariants({ size: "sm" })}>
              Set up
            </Link>
          </AlertDescription>
        </Alert>
      ) : null}
      <ExpiryAlerts />
      <Card>
        <CardHeader>
          <CardTitle>Add food</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {/* A scanned product starts a fresh form (the key remounts it). */}
          <PantryAdd
            key={scanned?.id ?? "search"}
            initialFood={scanned}
            onAdded={() => setScanned(null)}
            onCleared={() => setScanned(null)}
          />
          {scanned ? null : <BarcodeScan onFound={setScanned} />}
        </CardContent>
      </Card>
      <PantryList />
    </div>
  );
}
