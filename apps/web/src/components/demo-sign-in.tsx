"use client";

import { useAuth, useSignIn } from "@clerk/nextjs";
import { LoaderCircleIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { APP_NAME } from "@/lib/brand";

/**
 * Signs the visitor into the shared demo account with a one-use ticket from /api/demo, then
 * opens the plan. Someone already signed in just goes to their own plan.
 */
export function DemoSignIn() {
  const router = useRouter();
  const { isLoaded, isSignedIn } = useAuth();
  const { signIn } = useSignIn();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!isLoaded || started.current) return;
    started.current = true;
    if (isSignedIn) {
      router.replace("/plan");
      return;
    }
    void (async () => {
      try {
        const response = await fetch("/api/demo", { method: "POST" });
        const body = (await response.json()) as { ticket?: string; detail?: string[] };
        if (!response.ok || !body.ticket) {
          setError(body.detail?.[0] ?? "The demo is unavailable right now.");
          return;
        }
        const ticket = await signIn.ticket({ ticket: body.ticket });
        if (ticket.error) throw ticket.error;
        const done = await signIn.finalize({ navigate: () => router.replace("/plan") });
        if (done.error) throw done.error;
      } catch {
        setError("Couldn't open the demo. Try again in a moment.");
      }
    })();
  }, [isLoaded, isSignedIn, router, signIn]);

  if (error) {
    return (
      <div className="flex flex-col gap-3 text-center">
        <p role="alert">{error}</p>
        <Link href="/" className={buttonVariants({ variant: "outline" })}>
          Back to {APP_NAME}
        </Link>
      </div>
    );
  }
  return (
    <p className="flex items-center justify-center gap-2 text-muted-foreground" role="status">
      <LoaderCircleIcon aria-hidden className="size-4 animate-spin" />
      Opening the demo…
    </p>
  );
}
