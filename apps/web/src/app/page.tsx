import { connection } from "next/server";
import { Suspense } from "react";

import { ApiStatus } from "@/components/api-status";
import { getApiHealth } from "@/lib/api/health";

async function LiveApiStatus() {
  await connection(); // check on every request, never at build time
  return <ApiStatus status={await getApiHealth()} />;
}

export default function Home() {
  return (
    <main className="mx-auto flex min-h-full w-full max-w-md flex-col justify-center gap-4 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Larder</h1>
      <p className="text-zinc-600 dark:text-zinc-400">
        Plans your week around what&apos;s already in your kitchen.
      </p>
      <Suspense fallback={<ApiStatus status="checking" />}>
        <LiveApiStatus />
      </Suspense>
    </main>
  );
}
