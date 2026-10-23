import { Skeleton } from "@/components/ui/skeleton";

/** Shown while an app page's server part loads (client data has its own skeletons). */
export default function Loading() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-32" />
      <Skeleton className="h-32" />
    </div>
  );
}
