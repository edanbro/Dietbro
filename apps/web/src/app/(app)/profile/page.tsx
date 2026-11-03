import type { Metadata } from "next";
import { LegalLinks } from "@/components/legal-page";
import { ProfileIndex } from "@/components/profile/profile-index";

export const metadata: Metadata = { title: "Profile" };

export default function ProfilePage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-3xl font-semibold">Profile</h1>
      <ProfileIndex />
      <LegalLinks className="justify-center text-xs" />
    </div>
  );
}
