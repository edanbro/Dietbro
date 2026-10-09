"use client";

import Link from "next/link";

import { PantryAdd } from "@/components/pantry/pantry-add";
import { PantryList } from "@/components/pantry/pantry-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMe } from "@/lib/api/hooks";

export function PantryPage() {
  const { data: me } = useMe();
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Pantry</h1>
      {me && !me.setup_complete ? (
        <Alert>
          <AlertDescription className="flex items-center justify-between gap-2">
            Finish setting up so Larder can plan for you.
            <Link href="/setup" className={buttonVariants({ size: "sm" })}>
              Set up
            </Link>
          </AlertDescription>
        </Alert>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>Add food</CardTitle>
        </CardHeader>
        <CardContent>
          <PantryAdd />
        </CardContent>
      </Card>
      <PantryList />
    </div>
  );
}
