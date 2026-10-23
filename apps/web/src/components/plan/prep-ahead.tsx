"use client";

import { SnowflakeIcon, TimerIcon } from "lucide-react";
import Link from "next/link";

import { usePrepAhead } from "@/lib/api/hooks";
import { foodName } from "@/lib/food-name";

import { SLOT_LABEL } from "./slots";

/**
 * "Tonight, for tomorrow": what tomorrow's planned meals need doing the evening before, food to
 * take out of the freezer and steps to start (marinate overnight, soak the beans). Nothing to
 * do, nothing shown.
 */
export function PrepAhead() {
  const { data } = usePrepAhead();
  if (!data?.items.length) return null;
  return (
    <section
      aria-labelledby="prep-ahead"
      className="flex flex-col gap-2 rounded-lg border border-sky-600/30 bg-sky-500/5 px-3 py-2.5"
    >
      <h2 id="prep-ahead" className="text-sm font-medium">
        Tonight, for tomorrow
      </h2>
      <ul className="flex flex-col gap-2 text-sm">
        {data.items.map((item) => {
          const Icon = item.kind === "defrost" ? SnowflakeIcon : TimerIcon;
          return (
            <li key={`${item.kind}-${item.recipe_id}-${item.text}`} className="flex gap-2">
              <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-sky-700 dark:text-sky-400" />
              <span className="min-w-0">
                {item.kind === "defrost"
                  ? `Take the ${foodName(item.text).name.toLowerCase()} out of the freezer`
                  : item.text}
                <span className="block text-xs text-muted-foreground">
                  For{" "}
                  <Link
                    href={`/recipes/${item.recipe_id}`}
                    className="underline underline-offset-2 hover:text-foreground"
                  >
                    {item.recipe_name}
                  </Link>{" "}
                  ({SLOT_LABEL[item.slot].toLowerCase()})
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
