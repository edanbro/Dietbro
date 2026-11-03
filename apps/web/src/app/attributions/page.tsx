import type { Metadata } from "next";

import { LegalPage } from "@/components/legal-page";
import { APP_NAME } from "@/lib/brand";

export const metadata: Metadata = { title: "Data sources" };

const SOURCES = [
  {
    name: "USDA FoodData Central",
    what: "Generic foods (Foundation Foods, SR Legacy) and foods as eaten (survey foods, FNDDS).",
    licence: "Public domain.",
    href: "https://fdc.nal.usda.gov/",
  },
  {
    name: "McCance and Widdowson's The Composition of Foods Integrated Dataset 2021 (CoFID)",
    what: "UK and Irish foods as they're sold and eaten.",
    licence:
      "Contains public sector information licensed under the Open Government Licence v3.0.",
    href: "https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid",
  },
  {
    name: "Open Food Facts",
    what: "Packaged products sold in Ireland and the UK, with barcodes. Crowdsourced: always check the label.",
    licence:
      "© Open Food Facts contributors. Database under the Open Database License (ODbL); contents under the Database Contents License. Product photos are shown from Open Food Facts (not stored), under Creative Commons Attribution-ShareAlike (CC BY-SA). Nutrition grades use the Nutri-Score method; this app isn't affiliated with Nutri-Score.",
    href: "https://world.openfoodfacts.org/",
  },
  {
    name: "TheMealDB",
    what: "Recipes and their photos.",
    // Its terms: credit it as the source, and don't pass its artwork off as our own.
    licence:
      "From TheMealDB's free API, credited here as its terms ask. Most photos were added by TheMealDB's users and remain theirs.",
    href: "https://www.themealdb.com/",
  },
];

export default function AttributionsPage() {
  return (
    <LegalPage title="Data sources" current="/attributions" dated={false}>
      <p className="text-muted-foreground">
        {APP_NAME} plans with food and nutrition data from these sources. Thank you to everyone
        who makes them.
      </p>
      <ul className="flex flex-col gap-4">
        {SOURCES.map((s) => (
          <li key={s.name} className="flex flex-col gap-1">
            <a href={s.href} className="font-medium">
              {s.name}
            </a>
            <p className="text-sm">{s.what}</p>
            <p className="text-xs text-muted-foreground">{s.licence}</p>
          </li>
        ))}
      </ul>
      <p className="text-sm text-muted-foreground">
        Nutrition and allergen information is for planning only, not medical advice. Product
        data can be out of date or wrong.
      </p>
    </LegalPage>
  );
}
