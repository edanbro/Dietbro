/**
 * Cook once, eat twice, without the planner's help: tonight's dinner cooked in double and
 * eaten again at tomorrow's lunch is simply the same recipe in both places. The shopping list
 * and pantry already count both portions, so only the labels and the action live here.
 */

type MealLike = { slot: string; recipe: { id: number }; status?: string | null };
type DayLike = { date: string; meals: MealLike[] };

const key = (date: string, slot: string) => `${date}|${slot}`;

/** "date|slot" -> a note for the meal card, for each dinner whose leftovers are tomorrow's lunch. */
export function leftoverNotes(days: DayLike[]): Map<string, string> {
  const notes = new Map<string, string>();
  days.forEach((day, i) => {
    const next = days[i + 1];
    const dinner = day.meals.find((m) => m.slot === "dinner");
    const lunch = next?.meals.find((m) => m.slot === "lunch");
    if (!next || !dinner || !lunch || dinner.recipe.id !== lunch.recipe.id) return;
    notes.set(key(day.date, "dinner"), "Cook extra: it's tomorrow's lunch too");
    notes.set(key(next.date, "lunch"), "Leftovers from last night's dinner");
  });
  return notes;
}

export function noteFor(notes: Map<string, string>, date: string, slot: string) {
  return notes.get(key(date, slot));
}

/**
 * The date of tomorrow's lunch when this dinner can be cooked in double for it: a later day in
 * the plan with a lunch not eaten yet and not already this dish. Otherwise null.
 */
export function cookExtraFor(days: DayLike[], date: string, today: string): string | null {
  const i = days.findIndex((d) => d.date === date);
  const dinner = days[i]?.meals.find((m) => m.slot === "dinner");
  const next = days[i + 1];
  const lunch = next?.meals.find((m) => m.slot === "lunch");
  if (i < 0 || date < today || !dinner || dinner.status === "eaten" || !next || !lunch) return null;
  if (lunch.status === "eaten" || lunch.recipe.id === dinner.recipe.id) return null;
  return next.date;
}
