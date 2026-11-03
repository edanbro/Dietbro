import { SignUp } from "@clerk/nextjs";
import Link from "next/link";
import { Suspense } from "react";

import { APP_NAME } from "@/lib/brand";

export default function Page() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 px-4 py-8">
      <Suspense>
        <SignUp />
      </Suspense>
      {/* Told before signing up, not after (GDPR Article 13); consent is asked for in setup. */}
      <p className="max-w-sm text-center text-xs text-muted-foreground">
        By creating an account you agree to the{" "}
        <Link href="/terms" className="underline underline-offset-4">
          Terms
        </Link>
        . The{" "}
        <Link href="/privacy" className="underline underline-offset-4">
          Privacy policy
        </Link>{" "}
        says what {APP_NAME} keeps and why.
      </p>
    </main>
  );
}
