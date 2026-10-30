/**
 * The profile's sections, one page each (/profile/<id>): set up once and rarely changed, so the
 * profile is a short list to pick from rather than one long form with a save button per card.
 */
export const SECTIONS = [
  { id: "goals", title: "Goals", hint: "Calories, protein, budget", group: "Eating" },
  { id: "allergies", title: "Allergies", hint: "Never planned, whatever else", group: "Eating" },
  { id: "preferences", title: "Preferences", hint: "Diet, cuisines, foods", group: "Eating" },
  { id: "meals", title: "Meals to plan", hint: "Which meals we plan for you", group: "Eating" },
  { id: "busy-nights", title: "Busy nights", hint: "Quick dinners on these days", group: "Eating" },
  { id: "body", title: "Body stats", hint: "For calorie suggestions", group: "Eating" },
  { id: "templates", title: "Templates", hint: "Weeks saved to reuse", group: "Planning" },
  { id: "calendar", title: "Calendar", hint: "Meals in your calendar app", group: "Planning" },
  { id: "reminders", title: "Reminders", hint: "Use-by and evening notices", group: "Planning" },
  { id: "region", title: "Region", hint: "Prices, currency and units", group: "App" },
  { id: "appearance", title: "Appearance", hint: "Light, dark or system", group: "App" },
  { id: "account", title: "Your data", hint: "Download or delete it", group: "App" },
] as const;

export type SectionId = (typeof SECTIONS)[number]["id"];

export function sectionById(id: string) {
  return SECTIONS.find((s) => s.id === id);
}
