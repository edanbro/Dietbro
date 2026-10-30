import type { Metadata } from "next";
import Link from "next/link";

import { ProfileIndex } from "@/components/profile/profile-index";

export const metadata: Metadata = { title: "Profile" };

export default function ProfilePage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-3xl font-semibold">Profile</h1>
      <ProfileIndex />
      <Link
        href="/attributions"
        className="text-center text-xs text-muted-foreground underline-offset-4 hover:underline"
      >
        Data sources and licences
      </Link>
    </div>
  );
}
