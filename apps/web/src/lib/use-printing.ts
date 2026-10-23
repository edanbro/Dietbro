"use client";

import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

/**
 * True while the page is being printed (from beforeprint to afterprint). Print-only views
 * mount then, rendered synchronously so the printout has them, and stay out of the page
 * otherwise.
 */
export function usePrinting(): boolean {
  const [printing, setPrinting] = useState(false);
  useEffect(() => {
    const start = () => flushSync(() => setPrinting(true));
    const end = () => setPrinting(false);
    window.addEventListener("beforeprint", start);
    window.addEventListener("afterprint", end);
    return () => {
      window.removeEventListener("beforeprint", start);
      window.removeEventListener("afterprint", end);
    };
  }, []);
  return printing;
}
