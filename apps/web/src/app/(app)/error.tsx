"use client";

import { AlertCircleIcon } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { Button, buttonVariants } from "@/components/ui/button";

/** Something on an app page threw while rendering: say so and offer a retry. */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <div className="flex flex-col items-start gap-4 py-8" role="alert">
      <AlertCircleIcon className="size-8 text-destructive" aria-hidden />
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">Something went wrong</h1>
        <p className="text-sm text-muted-foreground">
          This page couldn&apos;t load. Try again, or go back to your plan.
        </p>
      </div>
      <div className="flex gap-2">
        <Button onClick={reset}>Try again</Button>
        <Link href="/plan" className={buttonVariants({ variant: "outline" })}>
          Your plan
        </Link>
      </div>
    </div>
  );
}
