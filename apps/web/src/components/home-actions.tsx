"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export function HomeActions() {
  const { isLoaded, isSignedIn } = useAuth();
  if (isLoaded && isSignedIn) {
    return (
      <Link href="/pantry" className={buttonVariants({ size: "lg" })}>
        Open Larder
      </Link>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <Link href="/sign-up" className={buttonVariants({ size: "lg" })}>
        Get started
      </Link>
      <Link href="/sign-in" className={buttonVariants({ size: "lg", variant: "ghost" })}>
        I have an account
      </Link>
    </div>
  );
}
