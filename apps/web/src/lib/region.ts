/**
 * Guess where the user lives from the browser, with no permission prompt: the time zone first
 * (Europe/Dublin is unambiguous, while many browsers in Ireland say en-US), then the region of
 * the preferred languages ("en-IE"). The user confirms the guess in setup and can change it in
 * Profile.
 */

/** IANA zones of the countries the API supports (GET /regions), zone -> ISO country. */
const ZONES: Record<string, string> = {
  "Europe/Dublin": "IE",
  "Europe/London": "GB",
  "Europe/Belfast": "GB",
  "Europe/Guernsey": "GB",
  "Europe/Isle_of_Man": "GB",
  "Europe/Jersey": "GB",
  "Europe/Vienna": "AT",
  "Europe/Brussels": "BE",
  "Europe/Zagreb": "HR",
  "Asia/Nicosia": "CY",
  "Asia/Famagusta": "CY",
  "Europe/Nicosia": "CY",
  "Europe/Tallinn": "EE",
  "Europe/Helsinki": "FI",
  "Europe/Paris": "FR",
  "Europe/Berlin": "DE",
  "Europe/Busingen": "DE",
  "Europe/Athens": "GR",
  "Europe/Rome": "IT",
  "Europe/Riga": "LV",
  "Europe/Vilnius": "LT",
  "Europe/Luxembourg": "LU",
  "Europe/Malta": "MT",
  "Europe/Amsterdam": "NL",
  "Europe/Lisbon": "PT",
  "Atlantic/Madeira": "PT",
  "Atlantic/Azores": "PT",
  "Europe/Bratislava": "SK",
  "Europe/Ljubljana": "SI",
  "Europe/Madrid": "ES",
  "Africa/Ceuta": "ES",
  "Atlantic/Canary": "ES",
  "Pacific/Honolulu": "US",
};

export type RegionGuess = {
  country: string | null; // null: couldn't tell, ask
  timezone: string | null;
  locale: string | null; // the browser language, when it is for the guessed country
};

export function guessRegion(
  timezone: string | null = browserTimezone(),
  languages: readonly string[] = browserLanguages(),
): RegionGuess {
  const fromZone = timezone ? zoneCountry(timezone) : null;
  const fromLanguage = languages.map(languageRegion).find((r) => r !== null) ?? null;
  const country = fromZone ?? fromLanguage;
  const locale = languages.find((l) => languageRegion(l) === country) ?? null;
  return { country, timezone, locale };
}

function zoneCountry(zone: string): string | null {
  if (zone in ZONES) return ZONES[zone];
  if (zone.startsWith("America/") && US_ZONE.test(zone)) return "US";
  return null;
}

// America/New_York, Chicago, Denver, Los_Angeles, Phoenix, Anchorage, Detroit, Boise, Indiana/*,
// Kentucky/*, North_Dakota/*, ... (not Toronto, Mexico_City etc.).
const US_ZONE =
  /^America\/(New_York|Chicago|Denver|Los_Angeles|Phoenix|Anchorage|Juneau|Sitka|Nome|Yakutat|Metlakatla|Adak|Detroit|Boise|Menominee|Indiana\/.+|Kentucky\/.+|North_Dakota\/.+)$/;

/** "en-IE" -> "IE", "ga" -> null. */
function languageRegion(tag: string): string | null {
  const region = tag.split(/[-_]/).slice(1).find((part) => /^[A-Za-z]{2}$/.test(part));
  return region ? region.toUpperCase() : null;
}

function browserTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

function browserLanguages(): readonly string[] {
  if (typeof navigator === "undefined") return [];
  return navigator.languages?.length ? navigator.languages : [navigator.language];
}

const SYMBOLS: Record<string, string> = { GBP: "£", EUR: "€", USD: "$" };

/** "€" for EUR (the receipt placeholder, short labels). */
export function currencySymbol(currency: string): string {
  return SYMBOLS[currency] ?? currency;
}
