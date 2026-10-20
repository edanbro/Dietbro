import { cn } from "cn"

/** A placeholder while content loads: a soft shimmer, or a still block for reduced motion. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "rounded-md bg-muted bg-[linear-gradient(90deg,transparent_25%,color-mix(in_oklch,var(--foreground)_6%,transparent)_50%,transparent_75%)] bg-size-[200%_100%] motion-safe:animate-shimmer",
        className
      )}
      {...props}
    />
  )
}

/** The shape of a meal card: photo, a label, a title and a line of numbers. */
function SkeletonMealCard() {
  return (
    <div className="flex items-center gap-3 rounded-xl border bg-card p-2.5">
      <Skeleton className="size-16 shrink-0 rounded-lg" />
      <div className="flex flex-1 flex-col gap-2">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    </div>
  )
}

/** The shape of list rows: a box or icon, then a line of text and a shorter one. */
function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div className="flex flex-col divide-y rounded-xl border bg-card">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-3">
          <Skeleton className="size-5 shrink-0 rounded" />
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-4" style={{ width: `${70 - ((i * 17) % 35)}%` }} />
            <Skeleton className="h-3 w-20" />
          </div>
        </div>
      ))}
    </div>
  )
}

export { Skeleton, SkeletonMealCard, SkeletonRows }
