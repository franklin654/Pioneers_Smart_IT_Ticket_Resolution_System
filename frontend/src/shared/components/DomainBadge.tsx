import type { Category } from "../../types";
import { DOMAIN_STYLES } from "../constants";

interface Props {
  category: Category;
}

export function DomainBadge({ category }: Props) {
  const { label, color } = DOMAIN_STYLES[category];
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium bg-${color}-500/20 text-${color}-300 border border-${color}-500/40`}
    >
      {label}
    </span>
  );
}
