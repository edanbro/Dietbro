"use client";

import { UserButton } from "@clerk/nextjs";
import { cn } from "cn";
import {
  BookOpenIcon,
  CalendarDaysIcon,
  NotebookPenIcon,
  RefrigeratorIcon,
  ShoppingCartIcon,
  UserIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { OfflineBanner } from "@/components/offline-banner";
import { useRegionSync } from "@/components/region-sync";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import { useMe, useOfflineSync } from "@/lib/api/hooks";
import { Logo } from "@/components/logo";

/** The everyday loop: plan, shop, cook, keep the kitchen and log what was eaten. `also`: pages
 * reached from a tab that keep it marked (the week in review opens from the diary). */
const NAV: { href: string; label: string; icon: typeof UserIcon; also?: string[] }[] = [
  { href: "/plan", label: "Plan", icon: CalendarDaysIcon },
  { href: "/plan/shopping", label: "Shopping", icon: ShoppingCartIcon },
  { href: "/recipes", label: "Recipes", icon: BookOpenIcon },
  { href: "/pantry", label: "Pantry", icon: RefrigeratorIcon },
  { href: "/diary", label: "Diary", icon: NotebookPenIcon, also: ["/recap"] },
];

/** The tab for a path: the longest matching href ("/plan/shopping" is Shopping, not Plan). */
export function activeTab(pathname: string): string | undefined {
  const under = (base: string) => pathname === base || pathname.startsWith(`${base}/`);
  return NAV.filter((n) => under(n.href) || n.also?.some(under))
    .map((n) => n.href)
    .sort((a, b) => b.length - a.length)[0];
}

/** Settings, set up once and rarely visited: the header (phone) and the rail's foot (desktop). */
const PROFILE = { href: "/profile", label: "Profile", icon: UserIcon };

/** The app's mark and name. */
function Brand() {
  return (
    <Link href="/plan">
      <Logo />
    </Link>
  );
}

/** Desktop side rail: the same places as the bottom bar, then the profile and the theme. */
function Rail({ pathname, expiring }: { pathname: string; expiring: number }) {
  const current = activeTab(pathname);
  const links = [...NAV, PROFILE];
  return (
    <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r bg-sidebar px-4 py-5 text-sidebar-foreground lg:flex print:hidden">
      <Brand />
      <nav aria-label="Sidebar" className="mt-8 flex-1">
        <ul className="flex flex-col gap-1">
          {links.map(({ href, label, icon: Icon }) => {
            const active = href === PROFILE.href ? pathname.startsWith(href) : current === href;
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-10 items-center gap-3 rounded-lg px-3 text-sm transition-colors",
                    active
                      ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                      : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
                  )}
                >
                  <Icon aria-hidden className="size-4" />
                  <span className="flex-1">{label}</span>
                  {href === "/pantry" && expiring ? (
                    <span className="rounded-full bg-warning-solid px-1.5 text-xs font-semibold text-white">
                      {expiring > 9 ? "9+" : expiring}
                      <span className="sr-only"> expiring soon</span>
                    </span>
                  ) : null}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="flex items-center justify-between gap-2">
        <ThemeToggle compact />
        <UserButton />
      </div>
    </aside>
  );
}

/** Mobile-first shell: compact header, content column, thumb-reach bottom nav; on wide screens
 * a side rail instead. */
/** Count bubble on a nav icon (the pantry's food expiring within 3 days). */
function CountBadge({ n }: { n: number }) {
  if (!n) return null;
  return (
    <span
      aria-hidden
      className="absolute -top-1.5 -right-2.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-warning-solid px-1 text-[10px] font-semibold text-white"
    >
      {n > 9 ? "9+" : n}
    </span>
  );
}

const IMMERSIVE = /^\/(recipes\/\d+\/cook|prep|setup)/;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: me } = useMe();
  useRegionSync(me, pathname.startsWith("/setup"));
  useOfflineSync();
  const expiring = me?.profile.expiring_soon ?? 0;
  // Cooking: the whole phone screen is the recipe, no tab bar to tap by accident. Setup:
  // nothing behind those tabs works until there's a first plan.
  const immersive = IMMERSIVE.test(pathname);
  return (
    // Printed: the page's content only, full width, no navigation.
    <div className="flex min-h-dvh flex-col lg:pl-64 print:min-h-0 print:pl-0">
      <a
        href="#main"
        className="sr-only z-30 rounded-md bg-background px-3 py-2 text-sm font-medium shadow focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <Rail pathname={pathname} expiring={expiring} />
      <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-background/95 px-4 backdrop-blur lg:hidden print:hidden">
        <Brand />
        <div className="flex items-center gap-1">
          {/* Settings aren't one of the tabs: a tap away from everywhere on a phone. */}
          <Link
            href="/profile"
            aria-label="Profile"
            aria-current={pathname.startsWith("/profile") ? "page" : undefined}
            className={cn(
              buttonVariants({ variant: "ghost", size: "icon" }),
              pathname.startsWith("/profile") && "text-primary",
            )}
          >
            <UserIcon aria-hidden />
          </Link>
          <UserButton />
        </div>
      </header>
      <div className="print:hidden">
        <OfflineBanner />
      </div>
      <main
        id="main"
        tabIndex={-1}
        className={cn(
          "mx-auto w-full max-w-md flex-1 px-4 pt-4 outline-none lg:max-w-4xl lg:px-10 lg:pt-10 lg:pb-12 print:max-w-none print:p-0",
          immersive ? "pb-8 md:max-w-3xl" : "pb-24",
        )}
      >
        {children}
      </main>
      {immersive ? null : (
        <nav
          aria-label="Main"
          className="fixed inset-x-0 bottom-0 z-10 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden print:hidden"
        >
          <ul className="mx-auto flex max-w-md">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = activeTab(pathname) === href;
              return (
                <li key={href} className="flex-1">
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    // One name, not label + sr-only text: browsers join those with a stray space.
                    aria-label={
                      href === "/pantry" && expiring
                        ? `${label}, ${expiring} expiring soon`
                        : undefined
                    }
                    className={cn(
                      "flex h-16 flex-col items-center justify-center gap-1 text-xs transition-colors",
                      active ? "font-medium text-primary" : "text-muted-foreground",
                    )}
                  >
                    <span className="relative">
                      <Icon className="size-5" />
                      {href === "/pantry" ? <CountBadge n={expiring} /> : null}
                    </span>
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
    </div>
  );
}
