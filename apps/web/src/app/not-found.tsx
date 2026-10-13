import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-4 px-6">
      <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>
      <p className="text-muted-foreground">
        That page doesn&apos;t exist, or it&apos;s someone else&apos;s.
      </p>
      <Link href="/plan" className={buttonVariants({ className: "self-start" })}>
        Go to your plan
      </Link>
    </main>
  );
}
