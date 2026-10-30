"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { SECTIONS, sectionById } from "./sections";

const GROUPS = [...new Set(SECTIONS.map((s) => s.group))];

/** The profile's sections as a list of links, grouped. Old links to a part of the one long page
 * (/profile#meals) open that section's own page. */
export function ProfileIndex() {
  const router = useRouter();
  useEffect(() => {
    const id = window.location.hash.slice(1);
    if (sectionById(id)) router.replace(`/profile/${id}`);
  }, [router]);

  return (
    <div className="flex flex-col gap-5">
      {GROUPS.map((group) => (
        <section key={group} aria-labelledby={`profile-${group}`} className="flex flex-col gap-2">
          <h2
            id={`profile-${group}`}
            className="text-xs font-medium tracking-wide text-muted-foreground uppercase"
          >
            {group}
          </h2>
          <ul className="flex flex-col divide-y rounded-xl border bg-card">
            {SECTIONS.filter((s) => s.group === group).map((s) => (
              <li key={s.id}>
                <Link
                  href={`/profile/${s.id}`}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60"
                >
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="text-sm font-medium">{s.title}</span>
                    <span className="text-xs text-muted-foreground">{s.hint}</span>
                  </span>
                  <ChevronRightIcon aria-hidden className="size-4 text-muted-foreground" />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
