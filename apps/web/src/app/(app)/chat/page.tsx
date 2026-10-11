import type { Metadata } from "next";

import { ChatPage } from "@/components/chat/chat-page";

export const metadata: Metadata = { title: "Chat · Larder" };

export default function Page() {
  return <ChatPage />;
}
