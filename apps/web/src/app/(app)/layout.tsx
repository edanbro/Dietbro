import { Suspense } from "react";

import { AppShell } from "@/components/app-shell";
import { Providers } from "@/components/providers";

// Client-rendered app pages (they read the URL and the signed-in session).
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Providers>
      <Suspense>
        <AppShell>{children}</AppShell>
      </Suspense>
    </Providers>
  );
}
