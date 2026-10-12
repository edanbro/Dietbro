"use client";

import { UserButton } from "@clerk/nextjs";
import { cn } from "cn";
import { CalendarDaysIcon, MessageCircleIcon, RefrigeratorIcon, UserIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useMe } from "@/lib/api/hooks";

const NAV = [
  { href: "/plan", label: "Plan", icon: CalendarDaysIcon },
  { href: "/chat", label: "Chat", icon: MessageCircleIcon },
  { href: "/pantry", label: "Pantry", icon: RefrigeratorIcon },
  { href: "/profile", label: "Profile", icon: UserIcon },
];

/** Mobile-first shell: compact header, content column, thumb-reach bottom nav. */
/** Count bubble on a nav icon (the pantry's food expiring within 3 days). */
function CountBadge({ n }: { n: number }) {
  if (!n) return null;
  return (
    <span
      aria-hidden
      className="absolute -top-1.5 -right-2.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-semibold text-white"
    >
      {n > 9 ? "9+" : n}
    </span>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: me } = useMe();
  const expiring = me?.profile.expiring_soon ?? 0;
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-background/95 px-4 backdrop-blur">
        <Link href="/plan" className="font-semibold tracking-tight">
          Larder
        </Link>
        <UserButton />
      </header>
      <main className="mx-auto w-full max-w-md flex-1 px-4 pt-4 pb-24">{children}</main>
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-10 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur"
      >
        <ul className="mx-auto flex max-w-md">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <li key={href} className="flex-1">
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-16 flex-col items-center justify-center gap-1 text-xs",
                    active ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  <span className="relative">
                    <Icon className="size-5" />
                    {href === "/pantry" ? <CountBadge n={expiring} /> : null}
                  </span>
                  {label}
                  {href === "/pantry" && expiring ? (
                    <span className="sr-only">, {expiring} expiring soon</span>
                  ) : null}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
