import type { ApiHealth } from "@/lib/api/health";

export type ApiStatusValue = ApiHealth | "checking";

const LABELS: Record<ApiStatusValue, string> = {
  checking: "checking…",
  ok: "ok",
  unreachable: "unreachable",
};

const DOT: Record<ApiStatusValue, string> = {
  checking: "bg-zinc-400",
  ok: "bg-emerald-500",
  unreachable: "bg-red-500",
};

export function ApiStatus({ status }: { status: ApiStatusValue }) {
  return (
    <p className="flex items-center gap-2 text-sm" data-api-status={status}>
      <span aria-hidden className={`size-2 rounded-full ${DOT[status]}`} />
      API: {LABELS[status]}
    </p>
  );
}
