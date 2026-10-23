"use client";

import { Link2Icon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { type ShareTarget, useRevokeShareLink, useShareLink } from "@/lib/api/hooks";

/**
 * Makes a read-only public link (a recipe, or a week's meals) and hands it to the phone's share
 * sheet, or copies it. The toast offers "Stop sharing", which turns the link off.
 */
export function ShareLinkButton({
  target,
  title,
  label = "Share",
  size = "sm",
  compact = false,
}: {
  target: ShareTarget;
  title: string;
  label?: string;
  size?: "sm" | "default";
  /** On phones, the label's first word only ("Share"); the rest stays for screen readers. */
  compact?: boolean;
}) {
  const create = useShareLink();
  const revoke = useRevokeShareLink();

  async function share() {
    let token: string;
    let url: string;
    try {
      const link = await create.mutateAsync(target);
      token = link.token;
      url = new URL(link.path, window.location.origin).toString();
    } catch {
      toast.error("Couldn't make a link. Try again.");
      return;
    }
    const stop = {
      label: "Stop sharing",
      onClick: () =>
        revoke.mutate(token, {
          onSuccess: () => toast.success("The link no longer works"),
          onError: () => toast.error("Couldn't turn the link off. Try again."),
        }),
    };
    try {
      if (navigator.share) {
        await navigator.share({ title, url });
        toast.success("Link shared", { action: stop });
        return;
      }
      await navigator.clipboard.writeText(url);
      toast.success("Link copied: anyone with it can see this", { action: stop });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return; // closed the share sheet
      toast.message(url, { description: "Copy this link to share it", action: stop });
    }
  }

  return (
    <Button variant="outline" size={size} disabled={create.isPending} onClick={() => void share()}>
      <Link2Icon aria-hidden />
      {compact ? <ShortLabel label={label} /> : label}
    </Button>
  );
}

/** "Share week": "Share" on phones, the whole label everywhere else and to screen readers. */
function ShortLabel({ label }: { label: string }) {
  const [first, ...rest] = label.split(" ");
  return (
    <>
      {first}
      {rest.length ? (
        <>
          {" "}
          <span className="max-sm:sr-only">{rest.join(" ")}</span>
        </>
      ) : null}
    </>
  );
}
