"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellIcon, BellOffIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { unwrap, useApi } from "@/lib/api/browser";

/** base64url -> bytes, for `applicationServerKey`. */
export function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const base64 = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4))
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function supported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration("/");
  return (await reg?.pushManager.getSubscription()) ?? null;
}

/**
 * Expiry reminders on this device: a notification at 9:00 your time when pantry food expires
 * today or tomorrow. Needs the installed or open app's service worker (production builds) and
 * the browser's permission.
 */
export function RemindersForm() {
  const api = useApi();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const config = useQuery({
    queryKey: ["me", "push"],
    queryFn: async () => unwrap(await api.GET("/me/push")),
  });
  const here = useQuery({
    queryKey: ["push-subscription"],
    enabled: supported(),
    queryFn: async () => Boolean(await currentSubscription()),
  });
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["me", "push"] }),
      qc.invalidateQueries({ queryKey: ["push-subscription"] }),
    ]);

  if (!supported()) {
    return (
      <p className="text-sm text-muted-foreground">
        This browser can&apos;t show reminders. On iPhone, add the app to your Home Screen first
        (Share, then Add to Home Screen).
      </p>
    );
  }
  if (config.data && !config.data.enabled) {
    return (
      <p className="text-sm text-muted-foreground">Reminders aren&apos;t set up on this server.</p>
    );
  }

  const turnOn = async () => {
    if (!config.data?.public_key) return;
    setBusy(true);
    try {
      if ((await Notification.requestPermission()) !== "granted") {
        toast.error("Notifications are blocked. Allow them in your browser's site settings.");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const sub =
        (await reg.pushManager.getSubscription()) ??
        (await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyBytes(config.data.public_key),
        }));
      const json = sub.toJSON();
      unwrap(
        await api.PUT("/me/push", {
          body: {
            endpoint: sub.endpoint,
            keys: { p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" },
          },
        }),
      );
      toast.success("Reminders on for this device");
    } catch {
      toast.error("Couldn't turn reminders on. Try again.");
    } finally {
      setBusy(false);
      await refresh();
    }
  };

  const turnOff = async () => {
    setBusy(true);
    try {
      const sub = await currentSubscription();
      if (sub) {
        unwrap(await api.POST("/me/push/unsubscribe", { body: { endpoint: sub.endpoint } }));
        await sub.unsubscribe();
      }
      toast.success("Reminders off for this device");
    } catch {
      toast.error("Couldn't turn reminders off. Try again.");
    } finally {
      setBusy(false);
      await refresh();
    }
  };

  const on = here.data === true;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        A notification at 9:00 when food in your pantry expires today or tomorrow.
      </p>
      <Button
        variant={on ? "outline" : "default"}
        disabled={busy || config.isPending || here.isPending}
        onClick={() => void (on ? turnOff() : turnOn())}
        className="self-start"
      >
        {on ? <BellOffIcon aria-hidden /> : <BellIcon aria-hidden />}
        {on ? "Turn off on this device" : "Turn on reminders"}
      </Button>
      {config.data && config.data.subscribed > (on ? 1 : 0) ? (
        <p className="text-xs text-muted-foreground">
          Also on in {config.data.subscribed - (on ? 1 : 0)} other{" "}
          {config.data.subscribed - (on ? 1 : 0) === 1 ? "browser" : "browsers"}.
        </p>
      ) : null}
    </div>
  );
}
