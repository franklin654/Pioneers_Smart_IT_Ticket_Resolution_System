import type { Classification } from "../../types";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { DomainBadge } from "./DomainBadge";

interface Props {
  classification: Classification;
}

export function ClassificationPanel({ classification: c }: Props) {
  return (
    <section aria-label="Classification details" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <DomainBadge category={c.predicted_category} />
        <ConfidenceBadge level={c.confidence_level} score={c.confidence} />
        {c.is_multi_domain && (
          <span className="rounded bg-violet-500/20 border border-violet-500/40 px-2 py-0.5 text-xs text-violet-300">
            Multi-domain
          </span>
        )}
      </div>
      {c.top_categories.length > 1 && (
        <ul className="text-xs text-slate-400 space-y-0.5" aria-label="Top categories">
          {c.top_categories.map((t) => (
            <li key={t.category} className="flex justify-between">
              <span>{t.category}</span>
              <span>{(t.probability * 100).toFixed(1)}%</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
