"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect } from "react";

import { buttonVariants } from "@/components/ui/button";
import { APP_NAME } from "@/lib/brand";
import { clearOfflineData } from "@/lib/offline";

export function HomeActions() {
  const { isLoaded, isSignedIn } = useAuth();
  // Signed out (sign-out lands here): no offline copies of anyone's plan stay on the device.
  useEffect(() => {
    if (isLoaded && !isSignedIn) clearOfflineData();
  }, [isLoaded, isSignedIn]);
  if (isLoaded && isSignedIn) {
    return (
      <Link href="/plan" className={buttonVariants({ size: "lg" })}>
        Open {APP_NAME}
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
