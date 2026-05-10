import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createThread,
  deleteThread,
  listThreads,
  updateThread,
} from "../api/threads";
import { useUser } from "../state/UserContext";

interface Props {
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: (id: string) => void;
  /** When true, the sidebar disables interactive actions. The active
   *  thread can still be highlighted but the user can't switch mid-stream. */
  locked?: boolean;
}

const STALE_MS = 24 * 60 * 60 * 1000; // 24h

function formatRelative(ts: number | null): string {
  if (!ts) return "no messages yet";
  const ms = Date.now() - ts * 1000;
  if (ms < 60_000) return "just now";
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

function isStale(ts: number | null): boolean {
  if (!ts) return false;
  return Date.now() - ts * 1000 > STALE_MS;
}

export default function ThreadsSidebar({
  activeId,
  onSelect,
  onCreate,
  locked = false,
}: Props) {
  const { userId, role } = useUser();
  const qc = useQueryClient();
  const ident = { userId, role };
  const [showArchived, setShowArchived] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const threadsQ = useQuery({
    queryKey: ["threads", userId, role, showArchived],
    queryFn: () => listThreads(ident, showArchived),
  });

  const create = useMutation({
    mutationFn: () => createThread(ident),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["threads", userId, role] });
      onCreate(t.thread_id);
    },
  });

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      updateThread(ident, id, { title }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["threads", userId, role] });
      setRenamingId(null);
    },
  });

  const archive = useMutation({
    mutationFn: ({ id, archived }: { id: string; archived: boolean }) =>
      updateThread(ident, id, { archived }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["threads", userId, role] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteThread(ident, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["threads", userId, role] });
    },
  });

  const threads = threadsQ.data?.threads ?? [];

  const onRenameSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!renamingId) return;
    const v = renameValue.trim();
    if (!v) {
      setRenamingId(null);
      return;
    }
    rename.mutate({ id: renamingId, title: v });
  };

  return (
    <aside className="border border-rule bg-paper-raised">
      <header className="px-4 py-3 border-b border-rule flex items-center justify-between">
        <div className="font-mono uppercase tracking-section text-[10px] text-ink-3">
          Investigations
        </div>
        <button
          type="button"
          disabled={locked || create.isPending}
          onClick={() => create.mutate()}
          className="font-mono text-[10px] uppercase tracking-section text-ink-2 hover:text-oxblood disabled:opacity-30 transition-colors"
          title="Start a new investigation"
        >
          + New
        </button>
      </header>

      <ul className="divide-y divide-rule max-h-[60vh] overflow-y-auto">
        {threadsQ.isLoading && (
          <li className="px-4 py-3 text-[12px] text-ink-3">loading…</li>
        )}
        {!threadsQ.isLoading && threads.length === 0 && (
          <li className="px-4 py-3 text-[12px] text-ink-3 italic">
            {showArchived
              ? "no archived investigations"
              : "no investigations yet — your first question opens one."}
          </li>
        )}
        {threads.map((t) => {
          const active = t.thread_id === activeId;
          const stale = isStale(t.last_message_at);
          const isRenaming = renamingId === t.thread_id;
          return (
            <li
              key={t.thread_id}
              className={`group relative ${
                active ? "bg-oxblood-soft" : "hover:bg-paper-sunken"
              } transition-colors`}
            >
              {isRenaming ? (
                <form onSubmit={onRenameSubmit} className="px-3 py-2 flex gap-2">
                  <input
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onBlur={() => setRenamingId(null)}
                    onKeyDown={(e) => {
                      if (e.key === "Escape") setRenamingId(null);
                    }}
                    className="flex-1 bg-paper border border-rule px-2 py-1 text-[12.5px] focus:outline-none focus:border-oxblood"
                    placeholder="title"
                  />
                </form>
              ) : (
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => onSelect(t.thread_id)}
                  className="w-full text-left px-4 py-2.5 disabled:cursor-not-allowed"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span
                      className={`text-[13px] truncate ${
                        active ? "text-ink font-medium" : "text-ink-2"
                      }`}
                    >
                      {t.title || "(untitled)"}
                    </span>
                    {active && (
                      <span className="font-mono text-[9px] uppercase tracking-section text-oxblood">
                        active
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 font-mono text-[10px] text-ink-4">
                    <span className="tnum">{formatRelative(t.last_message_at)}</span>
                    {stale && (
                      <span className="text-oxblood" title="Data may have changed since">
                        · stale
                      </span>
                    )}
                    {t.archived && <span>· archived</span>}
                  </div>
                </button>
              )}

              {/* Hover actions. Hidden when renaming or locked. */}
              {!isRenaming && !locked && (
                <div className="absolute right-2 top-2 hidden group-hover:flex items-center gap-1 bg-paper-raised border border-rule">
                  <ActionBtn
                    label="rename"
                    onClick={() => {
                      setRenamingId(t.thread_id);
                      setRenameValue(t.title ?? "");
                    }}
                  />
                  <ActionBtn
                    label={t.archived ? "unarchive" : "archive"}
                    onClick={() =>
                      archive.mutate({
                        id: t.thread_id,
                        archived: !t.archived,
                      })
                    }
                  />
                  <ActionBtn
                    label="delete"
                    danger
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete this investigation and all its messages?\n\n"${
                            t.title ?? "(untitled)"
                          }"`,
                        )
                      ) {
                        remove.mutate(t.thread_id);
                      }
                    }}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <footer className="px-4 py-2 border-t border-rule flex items-center justify-between">
        <button
          type="button"
          onClick={() => setShowArchived((v) => !v)}
          className="font-mono text-[10px] uppercase tracking-section text-ink-3 hover:text-ink transition-colors"
        >
          {showArchived ? "hide archived" : "show archived"}
        </button>
        <span className="font-mono text-[10px] text-ink-4 tnum">
          {threads.length}
        </span>
      </footer>
    </aside>
  );
}

function ActionBtn({
  label,
  onClick,
  danger,
}: {
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`px-2 py-0.5 text-[10px] font-mono uppercase tracking-section transition-colors ${
        danger ? "text-oxblood hover:bg-oxblood/10" : "text-ink-3 hover:text-ink hover:bg-paper-sunken"
      }`}
    >
      {label}
    </button>
  );
}
