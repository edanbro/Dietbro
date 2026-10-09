import type { Metadata } from "next";

import { ShoppingPage } from "@/components/shopping/shopping-page";

export const metadata: Metadata = { title: "Shopping list · Larder" };

export default function Page() {
  return <ShoppingPage />;
}
