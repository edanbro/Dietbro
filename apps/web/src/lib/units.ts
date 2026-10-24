/**
 * Weights and heights the way the user reads them: metric, or US (ounces and pounds, feet and
 * inches). The API always works in grams, kilograms and centimetres; only what's shown and
 * typed changes.
 */

import { formatGrams } from "./format";

export type Units = "metric" | "us";

const G_PER_OZ = 28.349523125;
const G_PER_LB = 453.59237;
const KG_PER_LB = G_PER_LB / 1000;
const CM_PER_IN = 2.54;

function trim(n: number, digits: number): string {
  return String(Number(n.toFixed(digits)));
}

/** "250 g" / "1.2 kg", or "9 oz" / "2.6 lb" (a pinch is "0.1 oz"). */
export function formatWeight(grams: number, units: Units): string {
  if (units === "metric") return formatGrams(grams);
  const oz = grams / G_PER_OZ;
  if (Math.abs(oz) < 1) return `${trim(oz, 1)} oz`;
  if (Math.abs(grams) < G_PER_LB) return `${Math.round(oz)} oz`;
  const lb = grams / G_PER_LB;
  return `${Math.abs(lb) < 100 ? trim(lb, 1) : Math.round(lb)} lb`;
}

/** The weight unit's short name: "kg" or "lb". */
export function bodyUnit(units: Units): "kg" | "lb" {
  return units === "us" ? "lb" : "kg";
}

/** A body weight in the user's unit, to one decimal place (a number, for inputs and charts). */
export function bodyWeight(kg: number, units: Units): number {
  return Number((units === "us" ? kg / KG_PER_LB : kg).toFixed(1));
}

/** "72.4 kg" or "159.6 lb". */
export function formatBodyWeight(kg: number, units: Units): string {
  return `${bodyWeight(kg, units)} ${bodyUnit(units)}`;
}

/** What the user typed, in their unit, back to kilograms (to 0.1 kg). */
export function kgFrom(value: number, units: Units): number {
  return Number((units === "us" ? value * KG_PER_LB : value).toFixed(1));
}

/** Centimetres as whole feet and inches: 178 -> [5, 10]. */
export function feetInches(cm: number): [number, number] {
  const inches = Math.round(cm / CM_PER_IN);
  return [Math.floor(inches / 12), inches % 12];
}

/** Feet and inches back to centimetres (to 0.1 cm). */
export function cmFrom(feet: number, inches: number): number {
  return Number(((feet * 12 + inches) * CM_PER_IN).toFixed(1));
}

/** A price per kilogram as the shopper compares it: per kg, or per lb in the US. */
export function perWeight(perKgMinor: number, units: Units): { minor: number; unit: "kg" | "lb" } {
  return units === "us"
    ? { minor: Math.round(perKgMinor * KG_PER_LB), unit: "lb" }
    : { minor: perKgMinor, unit: "kg" };
}
