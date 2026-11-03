import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, Section } from "@/components/legal-page";
import { APP_NAME } from "@/lib/brand";

export const metadata: Metadata = { title: "Cookie policy" };

// What the live site stores, checked in a browser on 2026-11-03 (docs/legal-review.md). Every
// item must stay strictly necessary: anything else would need a consent banner first.

const COOKIES = [
  {
    name: "__session",
    what: "Proves to each request that you're signed in. A short-lived token, renewed while you use the site.",
  },
  {
    name: "__client_uat",
    what: "When you last signed in or out, so a page knows whether to look for your session.",
  },
  {
    name: "__clerk_db_jwt",
    what: "Links this browser to Clerk while the site's sign-in runs in Clerk's development mode.",
  },
  {
    name: "clerk_active_context",
    what: "Which of your sessions is active.",
  },
];

const STORAGE = [
  { name: "theme", what: "Your choice of light or dark, if you pick one." },
  {
    name: "mw:…",
    what: "An offline copy of your plan and shopping list, and items ticked while offline. Removed when you sign out.",
  },
  {
    name: "__clerk_environment",
    what: "Clerk's sign-in settings, so the sign-in form loads quickly.",
  },
  {
    name: "Offline cache",
    what: "The app's files and the pages you've opened, so it works without a connection. Your pages are removed when you sign out.",
  },
];

function List({ items }: { items: { name: string; what: string }[] }) {
  return (
    <dl className="flex flex-col divide-y rounded-xl border">
      {items.map((c) => (
        <div key={c.name} className="flex flex-col gap-0.5 px-4 py-3">
          <dt className="font-mono text-sm break-all">{c.name}</dt>
          <dd className="text-sm text-muted-foreground">{c.what}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function CookiesPage() {
  return (
    <LegalPage title="Cookie policy" current="/cookies">
      <p>
        {APP_NAME} uses only the cookies and storage it needs to sign you in and to do what you
        ask, such as working offline. It has no analytics, advertising or social media cookies,
        and nothing that tracks you across sites.
      </p>

      <Section title="Why there's no cookie banner">
        <p>
          Ireland&apos;s ePrivacy Regulations (S.I. 336/2011, Regulation 5) need your consent
          before a site stores anything on your device, except what is strictly necessary for a
          service you asked for. Everything below is in that group, so there&apos;s nothing to
          ask about.
        </p>
      </Section>

      <Section title="Cookies">
        <p>
          All four are set by Clerk, the sign-in service, on this site&apos;s own address. Some
          have a copy with a short suffix on its name (for example{" "}
          <code className="font-mono text-sm">__session_kKhd_snF</code>), which is the same
          thing for this site&apos;s sign-in. Clerk may rename them, but they are all for
          signing in.
        </p>
        <List items={COOKIES} />
      </Section>

      <Section title="Storage in your browser">
        <p>Not cookies, but the same rules apply. None of it is sent anywhere.</p>
        <List items={STORAGE} />
        <p>
          If you turn reminders on, your browser also keeps a subscription for notifications.
          Turning reminders off in your profile or your browser removes it.
        </p>
      </Section>

      <Section title="Other sites">
        <p>
          Product and recipe photos load from Open Food Facts, TheMealDB and the sites of
          recipes you import. When checked in November 2026, those photos came with no cookies.
          The <Link href="/privacy">privacy policy</Link> explains what those sites can see.
        </p>
      </Section>

      <Section title="Your choices">
        <p>
          You can clear or block cookies and storage in your browser settings. If you block
          Clerk&apos;s cookies, you won&apos;t be able to sign in; clearing storage only removes
          offline copies and your theme.
        </p>
      </Section>
    </LegalPage>
  );
}
