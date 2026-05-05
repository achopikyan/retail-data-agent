import { FormEvent, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { streamChat } from "../api/chat";
import { submitFeedback } from "../api/feedback";
import { saveReport } from "../api/reports";
import MessageBubble from "../components/MessageBubble";
import { useUser } from "../state/UserContext";

type AgentVote = "up" | "down" | null;

interface Turn {
  id: string;
  index: number;
  user: string;
  agent: {
    text: string;
    done?: boolean;
    trace_id?: string;
    saveable?: boolean;
    saved?: boolean;
    vote?: AgentVote;
    nodeTrail: string[];
    error?: string;
  };
}

const NODE_LABEL: Record<string, string> = {
  router: "Routing",
  retrieve: "Searching golden bucket",
  sql_gen: "Drafting SQL",
  validate: "Validating",
  execute: "Querying warehouse",
  mask: "Masking PII",
  report: "Synthesising",
  graceful_fail: "Standing down",
};

const SUGGESTIONS = [
  "Top 10 customers by total spend",
  "Monthly revenue for the last 12 months",
  "Which categories drive revenue this quarter?",
  "Return rate by product category",
  "What columns does the orders table have?",
];

export default function ChatView() {
  const { userId, role } = useUser();
  const qc = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const listEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const updateTurn = (id: string, patch: Partial<Turn["agent"]>) => {
    setTurns((cur) =>
      cur.map((t) =>
        t.id === id ? { ...t, agent: { ...t.agent, ...patch } } : t,
      ),
    );
  };

  const submit = async (q: string) => {
    if (!q.trim() || streaming) return;
    setInput("");
    const id = `t-${Date.now()}`;
    const index = turns.length + 1;
    setTurns((cur) => [
      ...cur,
      {
        id,
        index,
        user: q.trim(),
        agent: { text: "", nodeTrail: [] },
      },
    ]);

    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChat({
        userId,
        role,
        question: q.trim(),
        signal: controller.signal,
        onEvent: (ev) => {
          if (ev.type === "open") {
            updateTurn(id, { trace_id: ev.trace_id });
          } else if (ev.type === "node") {
            const node = (ev.payload.node as string) ?? "";
            const evtName = (ev.payload.event as string) ?? "";
            if (node && evtName === "node_start") {
              setTurns((cur) =>
                cur.map((t) =>
                  t.id === id
                    ? {
                        ...t,
                        agent: {
                          ...t.agent,
                          nodeTrail: [
                            ...t.agent.nodeTrail,
                            NODE_LABEL[node] ?? node,
                          ],
                        },
                      }
                    : t,
                ),
              );
            }
          } else if (ev.type === "delta") {
            setTurns((cur) =>
              cur.map((t) =>
                t.id === id
                  ? {
                      ...t,
                      agent: { ...t.agent, text: (t.agent.text ?? "") + ev.text },
                    }
                  : t,
              ),
            );
          } else if (ev.type === "done") {
            updateTurn(id, {
              done: true,
              trace_id: ev.trace_id,
              saveable: ev.saveable,
              text: ev.report ?? ev.final_message ?? "",
            });
          } else if (ev.type === "error") {
            updateTurn(id, { done: true, error: ev.error });
          }
        },
      });
    } catch (err) {
      updateTurn(id, { done: true, error: String(err) });
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(input);
  };

  const cancel = () => abortRef.current?.abort();

  const handleSave = async (turn: Turn) => {
    const title = window.prompt("File this report under what title?")?.trim();
    if (!title) return;
    try {
      await saveReport({ userId, role }, { title, body: turn.agent.text });
      updateTurn(turn.id, { saved: true });
      qc.invalidateQueries({ queryKey: ["reports"] });
    } catch (err) {
      alert(`Save failed: ${err}`);
    }
  };

  const handleVote = async (turn: Turn, vote: "up" | "down") => {
    if (!turn.agent.trace_id) return;
    try {
      await submitFeedback({ userId, role }, { trace_id: turn.agent.trace_id, vote });
      updateTurn(turn.id, { vote });
      qc.invalidateQueries({ queryKey: ["feedback-stats"] });
    } catch (err) {
      alert(`Feedback failed: ${err}`);
    }
  };

  return (
    <section className="space-y-8">
      {/* ============================ HEADER STRIP ============================ */}
      <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-3">
        <div>
          <div className="eyebrow">§ 01 — The Briefing</div>
          <h2
            className="display mt-1"
            style={{ fontVariationSettings: '"SOFT" 50, "opsz" 72' }}
          >
            Ask the desk
          </h2>
        </div>
        <div className="hidden sm:block text-right">
          <div className="font-mono uppercase tracking-section text-[10px] text-ink-3">
            Turns this session
          </div>
          <div
            className="font-display text-[28px] leading-none tnum text-ink"
            style={{ fontVariationSettings: '"opsz" 72' }}
          >
            {turns.length.toString().padStart(2, "0")}
          </div>
        </div>
      </div>

      {/* ========================== SUGGESTIONS / EMPTY ======================= */}
      {turns.length === 0 && (
        <div className="grid gap-6 md:grid-cols-12 stagger">
          <div className="md:col-span-7">
            <p
              className="font-display text-[26px] leading-snug tracking-tight text-ink-2 italic"
              style={{ fontVariationSettings: '"SOFT" 100, "WONK" 0, "opsz" 60' }}
            >
              “Ask anything about sales, customers, products, or returns —
              the desk answers in plain English, with the figures behind
              every line.”
            </p>
            <div className="mt-6 text-[13px] text-ink-3 max-w-md leading-relaxed">
              Append <span className="font-mono text-ink">as a table</span>,{" "}
              <span className="font-mono text-ink">in bullets</span>, or{" "}
              <span className="font-mono text-ink">as prose</span> to set
              your standing format preference for future briefings.
            </div>
          </div>
          <div className="md:col-span-5">
            <div className="eyebrow mb-3">Today's prompts</div>
            <ul className="space-y-px border border-rule">
              {SUGGESTIONS.map((s, i) => (
                <li key={s}>
                  <button
                    type="button"
                    className="w-full text-left px-4 py-3 bg-paper-raised hover:bg-paper-sunken transition-colors flex items-baseline gap-3 group"
                    onClick={() => submit(s)}
                  >
                    <span className="font-mono text-[10px] text-ink-4 tnum group-hover:text-oxblood transition-colors">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="text-[13.5px] text-ink leading-snug">
                      {s}
                    </span>
                    <span className="ml-auto font-mono text-ink-4 group-hover:text-oxblood transition-colors">
                      →
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* ============================== TURNS ============================== */}
      {turns.length > 0 && (
        <div className="space-y-10">
          {turns.map((t, i) => {
            const isLast = i === turns.length - 1;
            const isStreaming = streaming && isLast && !t.agent.done;
            return (
              <div key={t.id} className="space-y-5">
                <MessageBubble role="user" index={t.index} text={t.user} />
                <MessageBubble
                  role="agent"
                  index={t.index}
                  streaming={isStreaming}
                  text={
                    t.agent.error ? `[error] ${t.agent.error}` : t.agent.text
                  }
                  meta={
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      {t.agent.nodeTrail.length > 0 && (
                        <span className="font-mono uppercase tracking-section text-[10px] text-ink-3">
                          {t.agent.done ? "✓" : "▸"}{" "}
                          {t.agent.nodeTrail.join(" · ")}
                        </span>
                      )}
                      {t.agent.trace_id && (
                        <span className="font-mono text-[10px] text-ink-4 ml-auto">
                          trace {t.agent.trace_id}
                        </span>
                      )}
                    </div>
                  }
                  footer={
                    t.agent.done && !t.agent.error && (
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          {t.agent.saveable && !t.agent.saved && (
                            <button
                              className="btn-secondary"
                              onClick={() => handleSave(t)}
                            >
                              File report
                            </button>
                          )}
                          {t.agent.saved && (
                            <span className="badge-good">Filed</span>
                          )}
                        </div>
                        <div className="flex items-center gap-1">
                          <span className="font-mono uppercase tracking-section text-[10px] text-ink-3 mr-2">
                            Mark
                          </span>
                          <VoteButton
                            vote="up"
                            current={t.agent.vote}
                            onClick={() => handleVote(t, "up")}
                          />
                          <VoteButton
                            vote="down"
                            current={t.agent.vote}
                            onClick={() => handleVote(t, "down")}
                          />
                        </div>
                      </div>
                    )
                  }
                />
              </div>
            );
          })}
          <div ref={listEndRef} />
        </div>
      )}

      {/* ============================== COMPOSER ============================== */}
      <form
        onSubmit={handleSubmit}
        className="sticky bottom-4 surface-elevated"
      >
        <div className="px-4 py-2 flex items-center justify-between border-b border-rule bg-paper-sunken">
          <span className="font-mono uppercase tracking-section text-[10px] text-ink-3">
            Compose · enter to send
          </span>
          <span className="font-mono text-[10px] text-ink-4 tnum">
            {input.length}/4000
          </span>
        </div>
        <div className="flex items-stretch">
          <input
            className="flex-1 bg-paper-raised px-4 py-3 text-[14px] text-ink placeholder:text-ink-3 focus:outline-none"
            placeholder={
              streaming
                ? "the desk is drafting…"
                : "What would you like the desk to investigate?"
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={streaming}
            maxLength={4000}
          />
          {streaming ? (
            <button
              type="button"
              className="px-5 bg-paper-raised border-l border-rule text-[13px] font-medium text-oxblood hover:bg-oxblood-soft transition-colors"
              onClick={cancel}
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              className="px-6 bg-ink text-paper text-[13px] font-medium tracking-tight border-l border-ink hover:bg-oxblood transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              disabled={!input.trim()}
            >
              Send →
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

interface VoteButtonProps {
  vote: "up" | "down";
  current: AgentVote | undefined;
  onClick: () => void;
}
function VoteButton({ vote, current, onClick }: VoteButtonProps) {
  const isUp = vote === "up";
  const active = current === vote;
  const disabled = current !== undefined && current !== null;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`w-7 h-7 inline-flex items-center justify-center text-[14px] border transition-all
        ${
          active
            ? isUp
              ? "border-verdigris bg-verdigris/15 text-verdigris"
              : "border-oxblood bg-oxblood/10 text-oxblood"
            : "border-rule text-ink-3 hover:border-ink-3 hover:text-ink"
        }
        ${disabled && !active ? "opacity-30" : ""}`}
      title={isUp ? "Up-vote (feeds the curator)" : "Down-vote"}
    >
      {isUp ? "↑" : "↓"}
    </button>
  );
}
