"use client";

import { useClerk, useUser } from "@clerk/nextjs";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorAlert, LabeledInput } from "@/components/form-bits";
import { Button } from "@/components/ui/button";
import { useDeleteAccount, useExport } from "@/lib/api/hooks";

/** GDPR basics: download everything we store; delete it all (and the sign-in account). */
export function AccountControls() {
  const exporter = useExport();
  const deleter = useDeleteAccount();
  const { user } = useUser();
  const { signOut } = useClerk();
  const [confirm, setConfirm] = useState("");

  function download() {
    exporter.mutate(undefined, { onSuccess: save });
  }

  function save(data: unknown) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: "larder-export.json" });
    a.click();
    URL.revokeObjectURL(url);
  }

  function deleteAccount() {
    deleter.mutate(undefined, {
      onSuccess: async () => {
        try {
          await user?.delete();
        } catch {
          // Our data is already gone. Clerk can refuse to delete the sign-in itself (e.g. it
          // wants a recent sign-in); sign out anyway rather than strand the user here.
          toast.error(
            "Your Larder data is deleted, but your sign-in couldn't be removed. Sign in again and delete it from your account settings.",
          );
          await signOut({ redirectUrl: "/" });
          return;
        }
        // Deleting the user ends its sessions, so signOut() would have nothing to do and
        // wouldn't redirect. A full load also drops everything cached in this tab.
        window.location.replace("/");
      },
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <Button variant="outline" onClick={download} disabled={exporter.isPending}>
        Download my data
      </Button>
      <ErrorAlert error={exporter.error} />
      <div className="flex flex-col gap-3 rounded-lg border border-destructive/40 p-3">
        <p className="text-sm">
          Delete your account and everything Larder stores about you. This can&apos;t be undone.
        </p>
        <LabeledInput
          id="confirm-delete"
          label='Type "delete" to confirm'
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="off"
        />
        <Button
          variant="destructive"
          disabled={confirm.trim().toLowerCase() !== "delete" || deleter.isPending}
          onClick={deleteAccount}
        >
          Delete my account
        </Button>
        <ErrorAlert error={deleter.error} />
      </div>
    </div>
  );
}
