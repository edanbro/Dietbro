import type { MetadataRoute } from "next";
import { APP_NAME } from "@/lib/brand";

/** Installable PWA ("Add to Home Screen"): cravings happen on phones. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: APP_NAME,
    short_name: APP_NAME,
    description: "Plans your week around what's already in your kitchen.",
    start_url: "/plan",
    display: "standalone",
    // The splash screen: the brand green's dark ground, so opening at night isn't a flash.
    background_color: "#121a16",
    theme_color: "#1d6b40",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      { name: "Shopping list", url: "/plan/shopping" },
      { name: "Pantry", url: "/pantry" },
    ],
  };
}
