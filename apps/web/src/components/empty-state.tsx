import type { ReactNode } from "react";

/**
 * Small line drawings for empty screens, in the theme's colours (light and dark): strokes in
 * the muted text colour, soft fills in the brand green and saffron.
 */
const ART = {
  plan: (
    <>
      <rect x="22" y="20" width="76" height="62" rx="10" className="fill-primary/10" />
      <path d="M22 38h76M42 14v12M78 14v12" />
      <rect x="22" y="20" width="76" height="62" rx="10" />
      <circle cx="44" cy="54" r="5" className="fill-brand-warm/40" />
      <circle cx="60" cy="54" r="5" className="fill-primary/30" />
      <circle cx="76" cy="54" r="5" className="fill-primary/30" />
      <circle cx="44" cy="69" r="5" className="fill-primary/30" />
      <circle cx="60" cy="69" r="5" className="fill-brand-warm/40" />
    </>
  ),
  pantry: (
    <>
      <path d="M18 84h84M18 52h84" />
      <rect x="26" y="26" width="18" height="26" rx="4" className="fill-brand-warm/30" />
      <path d="M28 26v-5h14v5" />
      <rect x="52" y="34" width="14" height="18" rx="3" className="fill-primary/20" />
      <path d="M74 52c0-10 4-16 10-16s10 6 10 16" className="fill-primary/10" />
      <rect x="30" y="62" width="24" height="22" rx="4" className="fill-primary/15" />
      <path d="M64 84V70a8 8 0 0 1 16 0v14" className="fill-brand-warm/25" />
    </>
  ),
  diary: (
    <>
      <rect x="30" y="14" width="60" height="74" rx="8" className="fill-primary/10" />
      <path d="M42 14v74M52 34h28M52 46h28M52 58h18" />
      <path d="M84 70l10-10 6 6-10 10h-6z" className="fill-brand-warm/40" />
    </>
  ),
  search: (
    <>
      <path d="M16 54h60a30 30 0 0 1-60 0z" className="fill-primary/15" />
      <path d="M46 54V40M46 44c0-8-6-12-14-12 0 8 6 12 14 12zM46 40c0-8 6-12 14-12 0 8-6 12-14 12z" />
      <circle cx="84" cy="36" r="12" className="fill-brand-warm/25" />
      <path d="M93 45l11 11" />
    </>
  ),
  shopping: (
    <>
      <path d="M28 36h64l-6 46H34z" className="fill-primary/15" />
      <path d="M44 36v-6a16 16 0 0 1 32 0v6" />
      <path d="M48 56l8 8 16-16" className="stroke-primary" />
    </>
  ),
} as const;

export type EmptyArt = keyof typeof ART;

export function EmptyIllustration({ art, className }: { art: EmptyArt; className?: string }) {
  return (
    <svg
      viewBox="0 0 120 96"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={`h-24 w-30 text-muted-foreground ${className ?? ""}`}
    >
      {ART[art]}
    </svg>
  );
}

/** A friendly empty screen: a drawing, a title, a line of help and usually one action. */
export function EmptyState({
  art,
  title,
  children,
  action,
}: {
  art: EmptyArt;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed px-6 py-10 text-center">
      <EmptyIllustration art={art} />
      <h2 className="text-xl font-semibold">{title}</h2>
      {children ? (
        <div className="max-w-sm text-sm text-pretty text-muted-foreground">{children}</div>
      ) : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
