import { cn } from "cn";
import Link from "next/link";

import { Logo } from "@/components/logo";
import { LEGAL_UPDATED } from "@/lib/legal";

const PAGES = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/cookies", label: "Cookies" },
  { href: "/attributions", label: "Data sources" },
] as const;

type Href = (typeof PAGES)[number]["href"];

/** The privacy policy, terms, cookie policy and data sources: one readable column each, public
 * (no sign-in), linked to one another. */
export function LegalPage({
  title,
  current,
  dated = true,
  children,
}: {
  title: string;
  current: Href;
  dated?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col gap-8 px-4 py-8 lg:py-12">
      <Link href="/" className="self-start">
        <Logo />
      </Link>
      <main className="flex flex-col gap-6">
        <header className="flex flex-col gap-1">
          <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
          {dated ? (
            <p className="text-sm text-muted-foreground">Last updated {LEGAL_UPDATED}</p>
          ) : null}
        </header>
        {/* Policy prose: plain lists get bullets, and links are underlined, not told apart by
            colour alone. */}
        <div className="flex flex-col gap-6 text-sm leading-relaxed sm:text-base [&_a]:underline [&_a]:underline-offset-4 [&_ul:not([class])]:flex [&_ul:not([class])]:list-disc [&_ul:not([class])]:flex-col [&_ul:not([class])]:gap-1.5 [&_ul:not([class])]:pl-5 [&_ul:not([class])>li]:pl-1">
          {children}
        </div>
      </main>
      <div className="mt-auto border-t pt-4">
        <LegalLinks current={current} className="text-sm" />
      </div>
    </div>
  );
}

/** The four pages as a row of links: these pages' foot, the landing page and the profile. */
export function LegalLinks({ current, className }: { current?: Href; className?: string }) {
  return (
    <nav aria-label="Legal">
      <ul className={cn("flex flex-wrap gap-x-5 gap-y-2", className)}>
        {PAGES.map((p) => (
          <li key={p.href}>
            <Link
              href={p.href}
              aria-current={p.href === current ? "page" : undefined}
              className={cn(
                "underline-offset-4 hover:underline",
                p.href === current ? "font-medium" : "text-muted-foreground",
              )}
            >
              {p.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** A titled part of a policy. */
export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {children}
    </section>
  );
}
