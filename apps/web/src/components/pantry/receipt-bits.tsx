"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import type { ReceiptStatus } from "@/lib/api/hooks";

/** "1 item", "3 items". */
export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

const STATUS: Record<
  ReceiptStatus,
  { label: string; variant: "secondary" | "destructive" | "default" | "outline" }
> = {
  queued: { label: "Reading…", variant: "secondary" },
  processing: { label: "Reading…", variant: "secondary" },
  ready: { label: "Ready to review", variant: "default" },
  failed: { label: "Failed", variant: "destructive" },
  confirmed: { label: "Added", variant: "outline" },
};

export function ReceiptStatusBadge({ status }: { status: ReceiptStatus }) {
  const { label, variant } = STATUS[status];
  return <Badge variant={variant}>{label}</Badge>;
}

export function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className={buttonVariants({ variant: "ghost", size: "sm", className: "-ml-2 self-start" })}
    >
      <ArrowLeftIcon aria-hidden />
      {children}
    </Link>
  );
}
