import type { ApplicationRead } from "@/hooks/use-job-applications";

export type AgeingLevel = "fresh" | "warning" | "critical";

const STAGE_TIMESTAMP: Record<ApplicationRead["stage"], keyof ApplicationRead | null> = {
  sourced: null,
  extracting: null,
  enriching: null,
  scored: null,
  validated: "validated_at",
  invited: "invited_at",
  scheduled: "scheduled_at",
  rejected: "rejected_at",
};

function pickStageTimestamp(app: ApplicationRead): string | null {
  const key = STAGE_TIMESTAMP[app.stage];
  if (key) {
    const value = app[key];
    if (typeof value === "string") return value;
  }
  return app.created_at ?? null;
}

function ageingLevel(elapsedMs: number): AgeingLevel {
  const days = elapsedMs / 86_400_000;
  if (days >= 14) return "critical";
  if (days >= 7) return "warning";
  return "fresh";
}

function formatLabel(elapsedMs: number): string {
  if (elapsedMs < 5 * 60_000) return "<1m";
  if (elapsedMs < 3600_000) {
    const m = Math.floor(elapsedMs / 60_000);
    return `${m}m`;
  }
  if (elapsedMs < 86_400_000) {
    const h = Math.floor(elapsedMs / 3600_000);
    return `${h}h`;
  }
  const d = Math.floor(elapsedMs / 86_400_000);
  return `${d}d`;
}

export function relativeTimeInStage(app: ApplicationRead): {
  label: string;
  ageingLevel: AgeingLevel;
} {
  const ts = pickStageTimestamp(app);
  if (!ts) return { label: "—", ageingLevel: "fresh" };
  const elapsed = Date.now() - new Date(ts).getTime();
  if (elapsed < 0) return { label: "<1m", ageingLevel: "fresh" };
  return { label: formatLabel(elapsed), ageingLevel: ageingLevel(elapsed) };
}
