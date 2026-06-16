import type { Resolution } from "../../types";

interface Props {
  resolution: Resolution;
}

export function RoutingPanel({ resolution: r }: Props) {
  return (
    <section aria-label="Routing details" className="space-y-2 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-slate-400">Decision:</span>
        <span className="capitalize font-medium text-slate-200">
          {r.routing_decision.replace("_", " ")}
        </span>
      </div>
      {r.escalation_reason && (
        <p className="text-amber-300 text-xs" role="alert">
          {r.escalation_reason}
        </p>
      )}
      {r.assigned_department && (
        <div className="flex items-center gap-2">
          <span className="text-slate-400">Department:</span>
          <span className="text-slate-200">{r.assigned_department}</span>
        </div>
      )}
      {r.llm_quality_score != null && (
        <div className="flex items-center gap-2">
          <span className="text-slate-400">Quality score:</span>
          <span className="text-slate-200">{r.llm_quality_score.toFixed(1)} / 5</span>
        </div>
      )}
    </section>
  );
}
