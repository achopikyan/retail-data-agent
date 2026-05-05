import { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { listAudit } from "../api/audit";
import { feedbackStats } from "../api/feedback";
import { useUser } from "../state/UserContext";

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
  });
}
function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function AuditView() {
  const { userId, role } = useUser();

  const auditQ = useQuery({
    queryKey: ["audit"],
    queryFn: () => listAudit({ userId, role }, 100),
    refetchInterval: 5_000,
  });

  const fbStats = useQuery({
    queryKey: ["feedback-stats"],
    queryFn: () => feedbackStats({ userId, role }),
    refetchInterval: 5_000,
  });

  const stats = [
    { label: "Total turns", value: fbStats.data?.total ?? "—" },
    { label: "Up-votes", value: fbStats.data?.up ?? "—", tone: "verdigris" as const },
    { label: "Down-votes", value: fbStats.data?.down ?? "—", tone: "oxblood" as const },
    { label: "Promoted to bucket", value: fbStats.data?.promoted ?? "—" },
  ];

  return (
    <section className="space-y-6">
      <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-3">
        <div>
          <div className="eyebrow">§ 03 — The Ledger</div>
          <h2
            className="display mt-1"
            style={{ fontVariationSettings: '"SOFT" 50, "opsz" 72' }}
          >
            Audit & feedback
          </h2>
        </div>
        <p className="hidden md:block max-w-sm text-right font-display italic text-[14px] text-ink-3 leading-snug">
          Every removal of a saved report is recorded — including the GDPR
          cross-author route — alongside the trace ID of the originating
          turn.
        </p>
      </div>

      {/* ============================== STATS ============================== */}
      <div className="grid grid-cols-2 md:grid-cols-4 border border-rule bg-paper-raised divide-x divide-rule stagger">
        {stats.map((s) => (
          <div key={s.label} className="px-5 py-5">
            <div className="font-mono uppercase tracking-section text-[10px] text-ink-3">
              {s.label}
            </div>
            <div
              className={`font-display text-[40px] leading-none tnum mt-2 ${
                s.tone === "oxblood"
                  ? "text-oxblood"
                  : s.tone === "verdigris"
                    ? "text-verdigris"
                    : "text-ink"
              }`}
              style={{ fontVariationSettings: '"opsz" 96' }}
            >
              {typeof s.value === "number"
                ? s.value.toString().padStart(2, "0")
                : s.value}
            </div>
          </div>
        ))}
      </div>

      {/* ============================== LEDGER ============================== */}
      <div className="surface">
        <div className="px-4 py-2.5 border-b border-rule bg-paper-sunken flex items-center justify-between">
          <span className="eyebrow">Audit log</span>
          <span className="font-mono text-[10px] uppercase tracking-section text-ink-3 inline-flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-verdigris animate-pulse-soft" />
            Live · 5s refresh
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="border-b border-rule bg-paper-sunken/50">
              <tr>
                <Th>When</Th>
                <Th>Actor</Th>
                <Th>Action</Th>
                <Th>Targets</Th>
                <Th>Reason</Th>
                <Th>Trace</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {!auditQ.data || auditQ.data.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-12 text-center font-display italic text-[14px] text-ink-3"
                  >
                    No entries.
                  </td>
                </tr>
              ) : (
                auditQ.data.map((a, i) => (
                  <tr
                    key={a.id}
                    className={`group hover:bg-paper-sunken transition-colors ${
                      i === 0 ? "animate-fade-up" : ""
                    }`}
                  >
                    <td className="px-4 py-2.5 align-top">
                      <div className="font-display text-[13px] text-ink leading-tight">
                        {fmtDate(a.ts)}
                      </div>
                      <div className="font-mono text-[10px] tnum text-ink-3">
                        {fmtTime(a.ts)}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 align-top font-mono text-[12.5px] text-ink">
                      {a.actor_id}
                    </td>
                    <td className="px-4 py-2.5 align-top">
                      <span
                        className={
                          a.action === "delete_gdpr"
                            ? "badge-warn"
                            : "badge-quiet"
                        }
                      >
                        {a.action}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 align-top font-mono text-[12px] text-ink-2 tnum">
                      {a.target_ids
                        .split(",")
                        .map((id) => `№${id.padStart(4, "0")}`)
                        .join(" · ")}
                    </td>
                    <td className="px-4 py-2.5 align-top text-[12.5px] text-ink-2 max-w-xs">
                      <span className="line-clamp-2">{a.reason || "—"}</span>
                    </td>
                    <td className="px-4 py-2.5 align-top font-mono text-[10.5px] text-ink-3">
                      {a.trace_id ?? "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-[11.5px] font-mono uppercase tracking-section text-ink-3">
        For per-node detail of a turn, run{" "}
        <span className="text-ink normal-case font-mono tracking-normal">
          python -m scripts.replay --latest --trace-id &lt;trace&gt;
        </span>{" "}
        on the host.
      </p>
    </section>
  );
}

function Th({ children }: { children: ReactNode }) {
  return (
    <th className="text-left font-mono uppercase tracking-section text-[10px] text-ink-3 font-medium px-4 py-2">
      {children}
    </th>
  );
}
