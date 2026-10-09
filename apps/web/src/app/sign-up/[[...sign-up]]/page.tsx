import { SignUp } from "@clerk/nextjs";
import { Suspense } from "react";

export default function Page() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-8">
      <Suspense>
        <SignUp />
      </Suspense>
    </main>
  );
}
