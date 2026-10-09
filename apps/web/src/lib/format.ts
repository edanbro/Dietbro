/** Display formatting shared by the plan, shopping and recipe screens. */

export type Currency = "GBP" | "EUR" | "USD";
export type Band = { min?: number | null; max?: number | null };
export type BandStatus = "below" | "within" | "above" | "none";

const NUMBER = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });

/** 1050 -> "1,050" */
export function formatNumber(n: number): string {
  return NUMBER.format(n);
}

const money = new Map<Currency, Intl.NumberFormat>();

/** Minor units (pence, cents) -> "£4.20", "€4.20", "$4.20". */
export function formatMoney(minor: number, currency: Currency): string {
  let fmt = money.get(currency);
  if (!fmt) {
    fmt = new Intl.NumberFormat("en-GB", {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
    });
    money.set(currency, fmt);
  }
  return fmt.format(minor / 100);
}

/** 450 -> "450 g", 1250 -> "1.3 kg", 2000 -> "2 kg". */
export function formatGrams(grams: number): string {
  if (Math.abs(grams) < 1000) return `${Math.round(grams)} g`;
  const kg = Math.round(grams / 100) / 10;
  return `${kg % 1 ? kg.toFixed(1) : kg} kg`;
}

/** Half-servings -> "×½", "×1", "×1½". */
export function formatServings(portions: number): string {
  const whole = Math.floor(portions / 2);
  const half = portions % 2 === 1;
  return `×${whole || (half ? "" : "0")}${half ? "½" : ""}`;
}

/** Half-servings -> "½ serving", "1 serving", "1½ servings" (for screen readers). */
export function servingsLabel(portions: number): string {
  const amount = formatServings(portions).slice(1);
  return `${amount} ${portions <= 2 ? "serving" : "servings"}`;
}

/** Where `value` sits against a band; "none" when there is no band to compare with. */
export function bandStatus(value: number, band: Band | null | undefined): BandStatus {
  const min = band?.min ?? null;
  const max = band?.max ?? null;
  if (min === null && max === null) return "none";
  if (min !== null && value < min) return "below";
  if (max !== null && value > max) return "above";
  return "within";
}

/** "1,800–2,200 kcal", "≥ 90 g", "≤ 70 g", or null without a band. */
export function formatBand(band: Band | null | undefined, unit: string): string | null {
  const min = band?.min ?? null;
  const max = band?.max ?? null;
  if (min !== null && max !== null) return `${formatNumber(min)}–${formatNumber(max)} ${unit}`;
  if (min !== null) return `≥ ${formatNumber(min)} ${unit}`;
  if (max !== null) return `≤ ${formatNumber(max)} ${unit}`;
  return null;
}

/** "tree_nuts" -> "Tree nuts" (fallback when the API's label isn't loaded). */
export function humanize(code: string): string {
  const words = code.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** API label for an allergen code, else a humanized code. */
export function allergenLabel(
  code: string,
  options?: readonly { code: string; label: string }[],
): string {
  return options?.find((o) => o.code === code)?.label ?? humanize(code);
}
