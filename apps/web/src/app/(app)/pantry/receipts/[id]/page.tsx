import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { ReceiptReview } from "@/components/pantry/receipt-review";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "Review receipt" };

async function Receipt({ params }: { params: PageProps<"/pantry/receipts/[id]">["params"] }) {
  const { id } = await params;
  if (!/^[1-9]\d{0,8}$/.test(id)) notFound();
  return <ReceiptReview id={Number(id)} />;
}

export default function Page({ params }: PageProps<"/pantry/receipts/[id]">) {
  // The id is request-time data (no generateStaticParams), so it's read inside Suspense.
  return (
    <Suspense fallback={<Skeleton className="h-40 w-full" />}>
      <Receipt params={params} />
    </Suspense>
  );
}
