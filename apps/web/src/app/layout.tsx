import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata, Viewport } from "next";

import "./globals.css";
import { APP_NAME } from "@/lib/brand";
import { THEME_SCRIPT } from "@/lib/theme";

/** Clerk's sign-in and account screens in the app's colours, light or dark (CSS variables). */
const CLERK_APPEARANCE = {
  variables: {
    colorPrimary: "var(--primary)",
    colorPrimaryForeground: "var(--primary-foreground)",
    colorBackground: "var(--card)",
    colorForeground: "var(--card-foreground)",
    colorMuted: "var(--muted)",
    colorMutedForeground: "var(--muted-foreground)",
    colorInput: "var(--background)",
    colorInputForeground: "var(--foreground)",
    colorBorder: "var(--border)",
    colorRing: "var(--ring)",
    colorDanger: "var(--destructive)",
    borderRadius: "0.75rem",
  },
};

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
    { media: "(prefers-color-scheme: light)", color: "#fcfcf9" },
    { media: "(prefers-color-scheme: dark)", color: "#121a16" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The theme script sets the html class before hydration, hence suppressHydrationWarning.
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col">
        <ClerkProvider
          appearance={CLERK_APPEARANCE}
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
