/**
 * The locale for numbers, money and dates: the user's region (from /me) once it's loaded,
 * "en-GB" until then. Number formatters are cached per locale and options.
 */

let current = "en-GB";

export function appLocale(): string {
  return current;
}

/** Switch the locale (ignored when the runtime doesn't know it). */
export function setAppLocale(locale: string): void {
  try {
    if (Intl.NumberFormat.supportedLocalesOf([locale]).length) current = locale;
  } catch {
    // an invalid tag: keep the current locale
  }
}

const numbers = new Map<string, Intl.NumberFormat>();

export function numberFormat(options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `${current}|${JSON.stringify(options)}`;
  let fmt = numbers.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat(current, options);
    numbers.set(key, fmt);
  }
  return fmt;
}

/** Not cached: a formatter keeps the time zone it was made in (tests change TZ). */
export function dateFormat(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat(current, options);
}
