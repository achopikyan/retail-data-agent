import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  deleteMatching,
  deleteReport,
  listReports,
  previewMatching,
} from "../api/reports";
import { Report } from "../api/types";
import ConfirmDialog from "../components/ConfirmDialog";
import GdprCountConfirmDialog from "../components/GdprCountConfirmDialog";
import { useUser } from "../state/UserContext";

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}
function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ReportsView() {
  const { userId, role } = useUser();
  const qc = useQueryClient();
  const [showAll, setShowAll] = useState(false);
  const [selected, setSelected] = useState<Report | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Report | null>(null);
  const [matchSubstring, setMatchSubstring] = useState("");
  const [matchPreview, setMatchPreview] = useState<{
    count: number;
    cross_user: boolean;
    mine: number;
    others: number;
  } | null>(null);
  const [gdprOpen, setGdprOpen] = useState(false);

  const reportsQ = useQuery({
    queryKey: ["reports", { all: showAll, userId, role }],
    queryFn: () => listReports({ userId, role }, showAll),
  });

  const deleteOne = useMutation({
    mutationFn: (r: Report) =>
      deleteReport({ userId, role }, r.id, "manual delete from desk"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
      if (selected?.id === confirmDelete?.id) setSelected(null);
      setConfirmDelete(null);
    },
    onError: (err: Error) => alert(`Delete failed: ${err.message}`),
  });

  const deleteMany = useMutation({
    mutationFn: (args: { substring: string; expected_count?: number }) =>
      deleteMatching(
        { userId, role },
        { ...args, reason: "delete-matching from desk" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
      setMatchSubstring("");
      setMatchPreview(null);
      setGdprOpen(false);
    },
    onError: (err: Error) => {
      alert(`Delete failed: ${err.message}`);
      setGdprOpen(false);
    },
  });

  const handlePreviewMatch = async () => {
    const sub = matchSubstring.trim();
    if (!sub) return;
    try {
      const preview = await previewMatching({ userId, role }, sub);
      const all = await listReports(
        { userId, role },
        role === "gdpr_officer",
      );
      const needle = sub.toLowerCase();
      const mine = all.filter(
        (r) =>
          r.owner_id === userId &&
          (r.title.toLowerCase().includes(needle) ||
            r.body.toLowerCase().includes(needle)),
      ).length;
      const others = preview.count - mine;
      setMatchPreview({
        count: preview.count,
        cross_user: preview.cross_user,
        mine,
        others,
      });
    } catch (err) {
      alert(`Preview failed: ${err}`);
    }
  };

  const triggerMatchDelete = () => {
    if (!matchPreview) return;
    if (matchPreview.cross_user) {
      setGdprOpen(true);
    } else if (
      window.confirm(
        `Delete ${matchPreview.count} report${matchPreview.count === 1 ? "" : "s"}?`,
      )
    ) {
      deleteMany.mutate({ substring: matchSubstring });
    }
  };

  const reports = reportsQ.data ?? [];

  return (
    <section className="space-y-6">
      {/* ============================ HEADER STRIP ============================ */}
      <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-3">
        <div>
          <div className="eyebrow">§ 02 — The Archive</div>
          <h2
            className="display mt-1"
            style={{ fontVariationSettings: '"SOFT" 50, "opsz" 72' }}
          >
            Saved reports
          </h2>
        </div>
        <div className="hidden sm:flex items-center gap-4">
          <Counter label="On file" value={reports.length} />
          {role === "gdpr_officer" && (
            <label className="flex items-center gap-2 text-[12px] text-ink-2">
              <input
                type="checkbox"
                checked={showAll}
                onChange={(e) => setShowAll(e.target.checked)}
                className="accent-oxblood"
              />
              <span className="font-mono uppercase tracking-section text-[10px]">
                Show all desks
              </span>
            </label>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-12 gap-6">
        {/* ============================ INDEX ============================ */}
        <aside className="lg:col-span-5 space-y-4">
          <div className="surface">
            <div className="px-4 py-2.5 border-b border-rule bg-paper-sunken flex items-baseline justify-between">
              <span className="eyebrow">Index</span>
              <span className="font-mono text-[10px] text-ink-3">
                {showAll ? "all desks" : userId}
              </span>
            </div>
            <div className="max-h-[60vh] overflow-y-auto divide-y divide-rule">
              {reportsQ.isLoading && (
                <div className="p-6 text-[12px] text-ink-3 italic font-display">
                  fetching…
                </div>
              )}
              {reportsQ.error && (
                <div className="p-4 text-[12px] text-oxblood">
                  {(reportsQ.error as Error).message}
                </div>
              )}
              {reports.length === 0 && !reportsQ.isLoading && (
                <div className="p-6 text-center text-[13px] text-ink-3 italic font-display">
                  No reports filed.
                </div>
              )}
              {reports.map((r) => {
                const isSelected = selected?.id === r.id;
                return (
                  <button
                    key={r.id}
                    className={`w-full text-left px-4 py-3 transition-colors group ${
                      isSelected
                        ? "bg-oxblood-soft"
                        : "hover:bg-paper-sunken"
                    }`}
                    onClick={() => setSelected(r)}
                  >
                    <div className="flex items-baseline gap-3">
                      <span
                        className={`font-mono text-[10px] tnum w-10 shrink-0 ${
                          isSelected ? "text-oxblood" : "text-ink-4"
                        }`}
                      >
                        {String(r.id).padStart(4, "0")}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div
                          className="font-display text-[15px] leading-snug tracking-tight text-ink truncate"
                          style={{
                            fontVariationSettings: '"SOFT" 30, "opsz" 36',
                          }}
                        >
                          {r.title}
                        </div>
                        <div className="font-mono text-[10px] uppercase tracking-section text-ink-3 mt-0.5">
                          {r.owner_id} · {fmtDate(r.created_at)} ·{" "}
                          {fmtTime(r.created_at)}
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ----------------------- Bulk delete tool ----------------------- */}
          <div className="surface">
            <div className="px-4 py-2.5 border-b border-rule bg-paper-sunken">
              <span className="eyebrow !text-oxblood">
                Bulk removal · GDPR
              </span>
            </div>
            <div className="p-4 space-y-3">
              <p className="text-[12px] text-ink-2 leading-relaxed">
                Remove every saved report whose title or body contains a
                phrase. Cross-author removals require the{" "}
                <span className="font-mono text-ink">gdpr</span> desk and
                count confirmation.
              </p>
              <div className="flex gap-0 border border-rule">
                <input
                  className="flex-1 bg-paper-raised px-3 py-2 text-[13px] focus:outline-none"
                  placeholder="phrase to match…"
                  value={matchSubstring}
                  onChange={(e) => {
                    setMatchSubstring(e.target.value);
                    setMatchPreview(null);
                  }}
                />
                <button
                  type="button"
                  className="px-3 bg-paper-sunken text-[12px] font-medium border-l border-rule hover:bg-rule transition-colors disabled:opacity-30"
                  onClick={handlePreviewMatch}
                  disabled={!matchSubstring.trim()}
                >
                  Preview
                </button>
              </div>
              {matchPreview && matchPreview.count > 0 && (
                <div className="flex items-center justify-between bg-paper-sunken border border-rule px-3 py-2">
                  <div className="text-[12px] text-ink-2">
                    Matches:{" "}
                    <span className="font-mono font-semibold text-ink tnum">
                      {matchPreview.count}
                    </span>
                    {matchPreview.others > 0 && (
                      <span className="text-oxblood">
                        {" "}
                        — {matchPreview.others} from other authors
                      </span>
                    )}
                  </div>
                  <button
                    className="btn-danger !py-1 !px-2 !text-[11px]"
                    onClick={triggerMatchDelete}
                  >
                    Remove {matchPreview.count}
                  </button>
                </div>
              )}
              {matchPreview && matchPreview.count === 0 && (
                <div className="text-[12px] text-ink-3 italic font-display">
                  No reports match.
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* ========================== READING PANE ========================== */}
        <main className="lg:col-span-7">
          {selected ? (
            <article className="surface">
              <header className="px-6 pt-6 pb-4 border-b border-rule">
                <div className="flex items-center justify-between">
                  <span className="eyebrow">Report №{String(selected.id).padStart(4, "0")}</span>
                  <button
                    className="btn-ghost !text-oxblood !text-[11px]"
                    onClick={() => setConfirmDelete(selected)}
                  >
                    Remove
                  </button>
                </div>
                <h1
                  className="display-lg !text-[34px] mt-2 leading-[1.05]"
                  style={{
                    fontVariationSettings: '"SOFT" 30, "opsz" 96',
                  }}
                >
                  {selected.title}
                </h1>
                <div className="font-mono uppercase tracking-section text-[10px] text-ink-3 mt-3 flex flex-wrap gap-x-4 gap-y-1">
                  <span>by {selected.owner_id}</span>
                  <span>{fmtDate(selected.created_at)}</span>
                  <span>{fmtTime(selected.created_at)}</span>
                </div>
              </header>
              <div className="px-6 py-5 max-h-[60vh] overflow-y-auto">
                <div className="report-md">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {selected.body}
                  </ReactMarkdown>
                </div>
              </div>
            </article>
          ) : (
            <div className="surface px-8 py-16 text-center">
              <div className="eyebrow justify-center mb-3">No selection</div>
              <p
                className="font-display text-[22px] leading-snug text-ink-2 italic"
                style={{ fontVariationSettings: '"SOFT" 100, "opsz" 60' }}
              >
                Choose a report from the index to read.
              </p>
            </div>
          )}
        </main>
      </div>

      <ConfirmDialog
        open={!!confirmDelete}
        title={
          confirmDelete
            ? `Remove “${confirmDelete.title}”?`
            : ""
        }
        description={
          confirmDelete && (
            <div className="space-y-2">
              <p>
                Filed by{" "}
                <span className="font-mono">{confirmDelete.owner_id}</span> on{" "}
                {fmtDate(confirmDelete.created_at)}.
              </p>
              {confirmDelete.owner_id !== userId && role !== "gdpr_officer" && (
                <p className="text-oxblood">
                  This report is not yours and your desk lacks the{" "}
                  <span className="font-mono">gdpr</span> mandate — the
                  removal will be refused server-side.
                </p>
              )}
            </div>
          )
        }
        confirmText="Remove"
        danger
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => confirmDelete && deleteOne.mutate(confirmDelete)}
      />

      <GdprCountConfirmDialog
        open={gdprOpen}
        expectedCount={matchPreview?.count ?? 0}
        substring={matchSubstring}
        ownerSummary={{
          mine: matchPreview?.mine ?? 0,
          others: matchPreview?.others ?? 0,
        }}
        onCancel={() => setGdprOpen(false)}
        onConfirm={(typed) =>
          deleteMany.mutate({
            substring: matchSubstring,
            expected_count: typed,
          })
        }
      />
    </section>
  );
}

function Counter({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="text-right">
      <div className="font-mono uppercase tracking-section text-[10px] text-ink-3">
        {label}
      </div>
      <div
        className="font-display text-[28px] leading-none tnum text-ink"
        style={{ fontVariationSettings: '"opsz" 72' }}
      >
        {typeof value === "number" ? value.toString().padStart(2, "0") : value}
      </div>
    </div>
  );
}
