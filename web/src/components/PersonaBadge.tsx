import { useQuery } from "@tanstack/react-query";

import { activePersona } from "../api/personas";
import { useUser } from "../state/UserContext";

export default function PersonaBadge() {
  const { userId, role } = useUser();
  const { data } = useQuery({
    queryKey: ["personas", "active"],
    queryFn: () => activePersona({ userId, role }),
    refetchInterval: 5_000,
  });
  if (!data) {
    return (
      <span className="font-mono uppercase tracking-section text-[10px] text-ink-3">
        Voice · loading…
      </span>
    );
  }
  return (
    <div className="flex items-center gap-2 group" title={data.description}>
      <span className="font-mono uppercase tracking-section text-[10px] text-ink-3">
        Voice
      </span>
      <span className="text-rule-strong font-mono">/</span>
      <span
        className="font-display text-[15px] tracking-tight text-ink transition-colors group-hover:text-oxblood"
        style={{ fontVariationSettings: '"SOFT" 30, "WONK" 1, "opsz" 36' }}
      >
        {data.name}
      </span>
    </div>
  );
}
