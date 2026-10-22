/** Light / Dark / System theme: a `dark` (or `light`) class on <html>, remembered per device. */

export type Theme = "light" | "dark" | "system";

export const THEME_KEY = "theme";

/**
 * Runs inline in <head> before the page paints (no flash of the wrong theme), and again when
 * the device switches between light and dark, on every page (the landing and share pages have
 * no theme toggle to listen for them). Kept tiny and self-contained; storage can throw
 * (private mode, blocked site data), then System applies.
 */
export const THEME_SCRIPT = `(function(){var m=matchMedia("(prefers-color-scheme: dark)");function a(){try{var t=localStorage.getItem("${THEME_KEY}")}catch(e){}var d=t==="dark"||(t!=="light"&&m.matches);var c=document.documentElement.classList;c.toggle("dark",d);c.toggle("light",!d)}a();m.addEventListener("change",a)})()`;

export function readTheme(): Theme {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function systemDark(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Apply `theme` to <html> (System follows the device) and remember it. */
export function applyTheme(theme: Theme): void {
  try {
    if (theme === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Not remembered; it still applies for this visit.
  }
  const dark = theme === "dark" || (theme === "system" && systemDark());
  const root = document.documentElement.classList;
  root.toggle("dark", dark);
  root.toggle("light", !dark);
}
