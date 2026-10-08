import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Larder",
  description: "AI meal planner that plans around your pantry.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
