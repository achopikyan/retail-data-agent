import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { activePersona } from "../api/personas";
import { useUser } from "../state/UserContext";

/**
 * Prominent strip showing which persona is drafting the current
 * investigation's reports. The persona is global today (yaml-driven),
 * but the strip lives on the chat view because that's where its
 * effect is most visible — the masthead badge is too easy to miss.
 *
 * Click-through navigates to /personas to change it.
 */
export default function ActivePersonaStrip() {
  const { userId, role } = useUser();
  const { data, isLoading } = useQuery({
    queryKey: ["personas", "active"],
    queryFn: () => activePersona({ userId, role }),
    refetchInterval: 5_000,
  });

  return (
    <Link
      to="/personas"
      title="Click to change the active persona"
      className="block border border-rule bg-paper-raised hover:bg-paper-sunken transition-colors group"
    >
      <div className="flex items-stretch divide-x divide-rule">
        {/* Eyebrow column */}
        <div className="px-4 py-2 flex flex-col justify-center">
          <span className="font-mono uppercase tracking-section text-[10px] text-ink-3">
            Drafting voice
          </span>
        </div>

        {/* Name + description */}
        <div className="flex-1 px-4 py-2 min-w-0">
          {isLoading || !data ? (
            <span className="font-mono text-[12px] text-ink-3">loading…</span>
          ) : (
            <div className="flex items-baseline gap-3 min-w-0">
              <span
                className="font-display text-[18px] tracking-tight text-ink group-hover:text-oxblood transition-colors whitespace-nowrap"
                style={{ fontVariationSettings: '"SOFT" 30, "WONK" 1, "opsz" 36' }}
              >
                {data.name}
              </span>
              <span className="text-[12.5px] text-ink-3 italic truncate">
                {data.description}
              </span>
            </div>
          )}
        </div>

        {/* Affordance */}
        <div className="px-4 py-2 flex items-center">
          <span className="font-mono text-[10px] uppercase tracking-section text-ink-4 group-hover:text-oxblood transition-colors">
            change →
          </span>
        </div>
      </div>
    </Link>
  );
}
