import type { Metadata } from "next";

import { DemoSignIn } from "@/components/demo-sign-in";

export const metadata: Metadata = { title: "Demo" };

export default function DemoPage() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-sm flex-col justify-center gap-4 px-6">
      <DemoSignIn />
    </main>
  );
}
