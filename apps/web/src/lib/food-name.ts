/**
 * Shopping-list names from USDA-style descriptions, which are written for a database index:
 * "Peppers, sweet, red, raw" becomes "Sweet red peppers", "Spices, turmeric, ground" becomes
 * "Ground turmeric" and "Beef, chuck, arm pot roast, separable lean only, ..." becomes "Beef"
 * with "chuck, arm pot roast" as a detail. Product names (no commas) come back unchanged.
 */

/** Parts that say nothing a shopper needs. */
const NOISE = [
  /^raw$/,
  /^commercially prepared$/,
  /^(un)?enriched$/,
  /^unbleached$/,
  /^year round average$/,
  /^includes skin$/,
  /^(meat|flesh) only$/,
  /^flesh and skin$/,
  /^separable lean( and fat)?( only)?$/,
  /^trimmed to /,
  /^(choice|select|all grades)$/,
  /^regular$/,
  /^salad or cooking$/,
  /^nfs$/,
  /^includes foods for usda/,
  /^broilers? or fryers$/,
  /^center cut$/,
  /^ripe$/,
  /^table$/,
  /^solids and liquids$/,
  /^without salt( added)?$/,
  /^ready[- ]to[- ]serve$/,
  /^bottled$/,
  /^home-prepared$/,
  /^unprepared$/,
  /^all$/,
];

/** Words that read naturally in front of the food: "red onions", "ground ginger". */
const ADJECTIVES = new Set([
  "red",
  "white",
  "yellow",
  "green",
  "brown",
  "black",
  "sweet",
  "hot",
  "whole-wheat",
  "wholemeal",
  "rye",
  "salted",
  "unsalted",
  "granulated",
  "smoked",
  "ground",
  "dried",
  "fresh",
  "frozen",
  "canned",
  "light",
  "dark",
  "powdered",
]);

/** Leading words that only file the food under a heading: "Spices, paprika" is paprika, and
 * "Alcoholic beverage, distilled, rum" is rum. */
const HEADINGS = new Set([
  "spices",
  "fish",
  "salad dressing",
  "beverages",
  "cereals",
  "sugars",
  "alcoholic beverage",
  "candies",
  "leavening agents",
  "crustaceans",
  "mollusks",
  "soup",
  "distilled",
  "carbonated",
]);
/** Headings that belong after the food: "Oil, olive" is olive oil. */
const TRAILING = new Set(["oil", "nuts", "seeds", "cheese", "vinegar", "sauce"]);
/** Meats are bought fresh anyway: "Pork, fresh, shoulder" is pork. */
const MEATS = new Set(["beef", "pork", "lamb", "veal"]);

export type FoodName = { name: string; detail: string | null };

function capitalise(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}

export function foodName(description: string): FoodName {
  const parts = description
    .replace(/\s*\(includes foods for usda[^)]*\)/gi, "")
    .split(/,(?![^(]*\))/) // not the commas inside brackets
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length < 2) return { name: description.trim(), detail: null };

  let [head, ...rest] = parts;
  rest = rest.filter((p) => !NOISE.some((re) => re.test(p.toLowerCase())));
  const lower = head!.toLowerCase();
  if (HEADINGS.has(lower) && rest.length) {
    while (HEADINGS.has(head!.toLowerCase()) && rest.length) head = rest.shift()!;
    // "Sugars, granulated" keeps its noun; "Soup, stock, chicken" is chicken stock.
    if (lower === "sugars" && ADJECTIVES.has(head!.toLowerCase())) head = `${head} sugar`;
    if (/^(stock|broth)$/i.test(head!) && rest.length) head = `${rest.shift()!} ${head}`;
    if (/^all \(gin/i.test(head!)) head = "spirits"; // "distilled, all (gin, rum, vodka...)"
  } else if (TRAILING.has(lower) && rest.length) {
    const first = rest.shift()!;
    const f = first.toLowerCase();
    // "Nuts, almonds" and "Seeds, sesame butter" are whole names already.
    const whole =
      f.endsWith(lower) ||
      ((lower === "nuts" || lower === "seeds") && /\s|s$|nut|seed/.test(f));
    head = whole ? first : `${first} ${lower}`;
  } else if (lower === "tomato products") {
    // "Tomato products, canned, paste" is canned tomato paste.
    const i = rest.findIndex((p) => !ADJECTIVES.has(p.toLowerCase()));
    if (i >= 0) head = `tomato ${rest.splice(i, 1)[0]!}`;
  } else if (lower === "bread" && rest[0]?.toLowerCase() === "crumbs") {
    rest.shift();
    head = "breadcrumbs";
  } else if (lower === "egg" && /^(white|yolk)$/i.test(rest[0] ?? "")) {
    head = `egg ${rest.shift()!.toLowerCase()}`;
    rest = rest.filter((p) => p.toLowerCase() !== "fresh");
  } else if (MEATS.has(lower)) {
    rest = rest.filter((p) => p.toLowerCase() !== "fresh");
  }

  const adjectives: string[] = [];
  while (rest.length && ADJECTIVES.has(rest[0]!.toLowerCase())) {
    adjectives.push(rest.shift()!.toLowerCase());
  }
  const name = capitalise([...adjectives, head!.toLowerCase()].join(" "));
  return { name, detail: rest.length ? rest.join(", ").toLowerCase() : null };
}

/**
 * "Uses your egg and carrots", "Uses your egg, carrots +2": what a recipe takes from the pantry,
 * by readable name (foodName), each food once.
 */
export function pantryUse(descriptions: readonly string[], shown = 2): string {
  return `Uses your ${shortList(descriptions, shown)}`;
}

/**
 * "Need rice", "Need rice and chilli", "Need rice, chilli +2", or "Nothing else to get": what a
 * recipe still needs that the pantry hasn't got.
 */
export function stillNeeded(descriptions: readonly string[], shown = 2): string {
  return descriptions.length ? `Need ${shortList(descriptions, shown)}` : "Nothing else to get";
}

/** Readable names (each once), the first `shown` of them, then how many more. */
function shortList(descriptions: readonly string[], shown: number): string {
  const names = [...new Set(descriptions.map((d) => foodName(d).name.toLowerCase()))];
  const first = names.slice(0, shown);
  const more = names.length - first.length;
  const list =
    first.length === 2 && !more ? `${first[0]} and ${first[1]}` : first.join(", ");
  return `${list}${more ? ` +${more}` : ""}`;
}
