import type { Metadata } from "next";

import { DiaryPage } from "@/components/diary/diary-page";

export const metadata: Metadata = { title: "Diary" };

export default function Page() {
  return <DiaryPage />;
}
