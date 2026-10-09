import type { MetadataRoute } from "next";

/** Installable PWA ("Add to Home Screen"): cravings happen on phones. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Larder",
    short_name: "Larder",
    description: "Plans your week around what's already in your kitchen.",
    start_url: "/pantry",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#ffffff",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
  };
}
