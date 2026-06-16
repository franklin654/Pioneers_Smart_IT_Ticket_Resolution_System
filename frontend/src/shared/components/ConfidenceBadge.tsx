import type { ConfidenceLevel } from "../../types";

const COLOR: Record<ConfidenceLevel, string> = {
  high: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  medium: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  low: "bg-rose-500/20 text-rose-300 border-rose-500/40",
};

interface Props {
  level: ConfidenceLevel;
  score?: number;
}

export function ConfidenceBadge({ level, score }: Props) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${COLOR[level]}`}
      aria-label={`Confidence: ${level}${score != null ? ` (${(score * 100).toFixed(0)}%)` : ""}`}
    >
      {level.toUpperCase()}
      {score != null && (
        <span className="opacity-70">({(score * 100).toFixed(0)}%)</span>
      )}
    </span>
  );
}
