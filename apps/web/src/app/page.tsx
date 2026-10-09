import { connection } from "next/server";
import { Suspense } from "react";

import { ApiStatus } from "@/components/api-status";
import { HomeActions } from "@/components/home-actions";
import { getApiHealth } from "@/lib/api/health";

async function LiveApiStatus() {
  await connection(); // check on every request, never at build time
  return <ApiStatus status={await getApiHealth()} />;
}

export default function Home() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-6 px-6 py-16">
      <div className="flex flex-col gap-3">
        <h1 className="text-4xl font-semibold tracking-tight">Larder</h1>
        <p className="text-lg text-muted-foreground">
          Plans your week around what&apos;s already in your kitchen, and re-plans when life
          happens.
        </p>
      </div>
      <HomeActions />
      <Suspense fallback={<ApiStatus status="checking" />}>
        <LiveApiStatus />
      </Suspense>
    </main>
  );
}
