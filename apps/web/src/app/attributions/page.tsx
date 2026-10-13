import type { Metadata } from "next";
import Link from "next/link";

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
      "© Open Food Facts contributors. Database under the Open Database License (ODbL); contents under the Database Contents License. No product images are stored.",
    href: "https://world.openfoodfacts.org/",
  },
  {
    name: "TheMealDB",
    what: "Recipes.",
    licence: "Used through its free API.",
    href: "https://www.themealdb.com/",
  },
];

export default function AttributionsPage() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col gap-5 px-4 py-8">
      <h1 className="text-2xl font-semibold tracking-tight">Data sources</h1>
      <p className="text-sm text-muted-foreground">
        {APP_NAME} plans with food and nutrition data from these sources. Thank you to everyone
        who makes them.
      </p>
      <ul className="flex flex-col gap-4">
        {SOURCES.map((s) => (
          <li key={s.name} className="flex flex-col gap-1">
            <a href={s.href} className="font-medium underline-offset-4 hover:underline">
              {s.name}
            </a>
            <p className="text-sm">{s.what}</p>
            <p className="text-xs text-muted-foreground">{s.licence}</p>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        Nutrition and allergen information is for planning only, not medical advice. Product
        data can be out of date or wrong.
      </p>
      <Link href="/" className="text-sm underline-offset-4 hover:underline">
        Back
      </Link>
    </main>
  );
}
