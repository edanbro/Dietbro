import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata, Viewport } from "next";

import "./globals.css";
import { APP_NAME } from "@/lib/brand";

export const metadata: Metadata = {
  title: { default: APP_NAME, template: `%s · ${APP_NAME}` },
  description: "Plans your week around what's already in your kitchen.",
  applicationName: APP_NAME,
  appleWebApp: { capable: true, title: APP_NAME, statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <ClerkProvider
          proxyUrl="/__clerk"
          signInUrl="/sign-in"
          signUpUrl="/sign-up"
          signInFallbackRedirectUrl="/plan"
          signUpFallbackRedirectUrl="/setup"
          afterSignOutUrl="/"
        >
          {children}
        </ClerkProvider>
      </body>
    </html>
  );
}
