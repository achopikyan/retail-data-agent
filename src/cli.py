"""CLI entrypoint for the retail data analysis agent.

Usage:
    python -m src.cli
"""
from __future__ import annotations

import logging
import sys
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Optional

from src import settings
from src.graph.builder import build_graph
from src.llm.gemini import GeminiLLM
from src.obs.log import SessionLog, counters_snapshot, setup_logging
from src.tools import feedback_store, prefs_store, reports_store
from src.tools.bq import BigQueryRunner, get_schema_summary
from src.tools.golden_bucket import GoldenBucket
from src.tools.persona import load_active_persona
from src.tools.reports_store import GDPR_ROLE


HELP = """\
Available commands:
  /help                       — show this help
  /persona                    — show the active persona
  /counters                   — show in-process metrics
  /login <user> [role]        — switch active user. role in {manager, gdpr_officer}.
                                Default role: manager.
  /whoami                     — show current user + role
  /save <title>               — save the most recent report
  /reports [--all]            — list saved reports (your own; --all for everyone)
  /show <id>                  — show a saved report
  /delete <id>                — delete a saved report (asks for confirmation)
  /delete-matching <text>     — delete all matching reports (asks for confirmation)
  /audit [N]                  — show last N audit log entries (default 10)
  /up                         — thumbs-up the most recent report
  /down                       — thumbs-down the most recent report
  /feedback                   — show feedback stats (total, up, down, promoted)
  /prefs                      — show your preferences
  /prefs set <key>=<value>    — set a pref (key in {report_format, default_time_window, preferred_currency})
  /quit                       — exit

Anything else is treated as a natural-language question against the
thelook_ecommerce dataset (orders, order_items, products, users).
"""


@dataclass
class Session:
    """Per-process state held by the CLI loop."""
    current_user: str
    current_role: str = "manager"
    last_trace_id: Optional[str] = None
    last_report: Optional[str] = None
    last_question: Optional[str] = None
    pending_action: Optional[dict] = field(default=None)


# --- helpers ---------------------------------------------------------------


def _ts(t: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")


def _print_banner(session_log: SessionLog, schema: str, user: str, role: str) -> None:
    print("Retail Data Analysis Agent — interactive CLI")
    print(f"Session log: {session_log.path}")
    print(f"Active persona: {load_active_persona().name}")
    print(f"User: {user}  (role: {role})")
    print("Tables in scope:")
    for line in schema.splitlines():
        print("  " + line)
    print("\nType /help for commands. Ctrl-D or /quit to exit.\n")


def _confirm(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in {"y", "yes"}


# --- command handlers ------------------------------------------------------


def cmd_login(s: Session, args: str) -> None:
    parts = args.strip().split()
    if not parts:
        print(f"current user: {s.current_user}  role: {s.current_role}")
        return
    user = parts[0]
    role = parts[1] if len(parts) > 1 else "manager"
    if role not in {"manager", GDPR_ROLE}:
        print(f"role must be one of: manager, {GDPR_ROLE}")
        return
    s.current_user = user
    s.current_role = role
    print(f"now logged in as {user} (role: {role})")


def cmd_whoami(s: Session) -> None:
    print(f"user={s.current_user}  role={s.current_role}")


def cmd_save(s: Session, title: str) -> None:
    title = title.strip()
    if not title:
        print("usage: /save <title>")
        return
    if not s.last_report:
        print("nothing to save — ask a question first")
        return
    rid = reports_store.save(s.current_user, title, s.last_report)
    print(f"saved report #{rid}: {title!r} ({s.current_user})")


def cmd_reports(s: Session, args: str) -> None:
    show_all = "--all" in args.split()
    owner = None if show_all else s.current_user
    reports = reports_store.list_for(owner)
    if not reports:
        print("(no reports)")
        return
    for r in reports:
        body_preview = r.body.splitlines()[0][:80] if r.body else ""
        print(f"  #{r.id:<4}  [{r.owner_id:<12}]  {r.title:<35}  {_ts(r.created_at)}")
        print(f"         └─ {body_preview}")


def cmd_show(s: Session, args: str) -> None:
    try:
        rid = int(args.strip())
    except ValueError:
        print("usage: /show <id>")
        return
    r = reports_store.get(rid)
    if not r:
        print(f"no report with id {rid}")
        return
    print(f"#{r.id}  {r.title}")
    print(f"owner: {r.owner_id}  saved: {_ts(r.created_at)}")
    print("---")
    print(r.body)


def _request_delete_confirmation(s: Session, target_ids: list[int], reason: str) -> None:
    """Stage a pending delete; the next user input is the confirmation."""
    if not target_ids:
        print("(nothing to delete)")
        return
    matched = [reports_store.get(i) for i in target_ids]
    matched = [m for m in matched if m]
    not_owned = [m.id for m in matched if m.owner_id != s.current_user]
    cross_user = bool(not_owned) and s.current_role != GDPR_ROLE

    print(f"\nThis will delete {len(matched)} report(s):")
    for m in matched:
        flag = "" if m.owner_id == s.current_user else f"  ⚠ owned by {m.owner_id}"
        print(f"  #{m.id}  {m.title}{flag}")

    if cross_user:
        print(
            f"\n⚠ {len(not_owned)} report(s) are not yours and your role is "
            f"'{s.current_role}'. Cross-user deletes require the '{GDPR_ROLE}' role."
        )
        return

    if s.current_role == GDPR_ROLE and not_owned:
        # GDPR cross-user delete: require typing the count to proceed.
        s.pending_action = {
            "kind": "delete_gdpr",
            "ids": target_ids,
            "reason": reason,
            "expected_count": len(matched),
        }
        print(
            f"\nGDPR cross-user delete. To confirm, type the exact report count "
            f"({len(matched)}) on the next line."
        )
    else:
        s.pending_action = {"kind": "delete", "ids": target_ids, "reason": reason}
        print("\nType 'yes' to confirm, anything else to cancel.")


def cmd_delete(s: Session, args: str) -> None:
    try:
        rid = int(args.strip())
    except ValueError:
        print("usage: /delete <id>")
        return
    if not reports_store.get(rid):
        print(f"no report with id {rid}")
        return
    _request_delete_confirmation(s, [rid], reason=f"/delete {rid}")


def cmd_delete_matching(s: Session, text: str) -> None:
    text = text.strip()
    if not text:
        print("usage: /delete-matching <text>")
        return
    # gdpr_officer can match across users; managers only their own.
    owner = None if s.current_role == GDPR_ROLE else s.current_user
    matched = reports_store.find_matching(text, owner_id=owner)
    if not matched:
        print(f"(no reports match {text!r})")
        return
    _request_delete_confirmation(s, [m.id for m in matched], reason=f"/delete-matching {text!r}")


def _consume_pending(s: Session, user_input: str, trace_id: Optional[str]) -> bool:
    """If there's a pending confirmation, treat user_input as the confirmation.

    Returns True when the input was consumed (so the main loop should not
    treat it as a new question).
    """
    if not s.pending_action:
        return False

    action = s.pending_action
    s.pending_action = None  # one-shot, regardless of outcome

    if action["kind"] == "delete":
        if user_input.strip().lower() in {"y", "yes"}:
            try:
                deleted = reports_store.delete_ids(
                    action["ids"],
                    actor_id=s.current_user,
                    actor_role=s.current_role,
                    reason=action.get("reason", ""),
                    trace_id=trace_id,
                )
                print(f"deleted {deleted} report(s).")
            except PermissionError as e:
                print(f"refused: {e}")
        else:
            print("cancelled.")
        return True

    if action["kind"] == "delete_gdpr":
        try:
            typed = int(user_input.strip())
        except ValueError:
            print("cancelled (expected the report count as a number).")
            return True
        if typed != action["expected_count"]:
            print(
                f"cancelled — expected {action['expected_count']}, got {typed}. "
                "Cross-user GDPR deletes require typing the exact count."
            )
            return True
        try:
            deleted = reports_store.delete_ids(
                action["ids"],
                actor_id=s.current_user,
                actor_role=s.current_role,
                reason=action.get("reason", ""),
                trace_id=trace_id,
            )
            print(f"deleted {deleted} report(s) under GDPR authority.")
        except PermissionError as e:
            print(f"refused: {e}")
        return True

    return False


def cmd_audit(s: Session, args: str) -> None:
    n = 10
    parts = args.split()
    if parts:
        try:
            n = int(parts[0])
        except ValueError:
            pass
    rows = reports_store.audit_recent(limit=n)
    if not rows:
        print("(audit log is empty)")
        return
    for r in rows:
        print(
            f"  {_ts(r['ts'])}  {r['actor_id']:<14}  {r['action']:<14}  "
            f"ids={r['target_ids']}  reason={r['reason'] or ''}"
        )


def cmd_up_down(s: Session, fb: str) -> None:
    if not s.last_trace_id:
        print("no recent turn to vote on")
        return
    ok = feedback_store.set_feedback(s.last_trace_id, fb)
    if ok:
        print(f"recorded {fb} for trace {s.last_trace_id}")
    else:
        print("(no matching pending_trios row — was the last turn a real analysis?)")


def cmd_feedback(s: Session) -> None:
    st = feedback_store.stats()
    print(f"  total:    {st['total']}")
    print(f"  up:       {st['up']}")
    print(f"  down:     {st['down']}")
    print(f"  promoted: {st['promoted']}")


def cmd_prefs(s: Session, args: str) -> None:
    parts = args.strip().split(maxsplit=1)
    if not parts:
        prefs = prefs_store.get_prefs(s.current_user)
        if not prefs:
            print(f"(no preferences set for {s.current_user})")
        else:
            for k, v in sorted(prefs.items()):
                print(f"  {k} = {v}")
        return
    if parts[0] == "set":
        if len(parts) < 2 or "=" not in parts[1]:
            print("usage: /prefs set <key>=<value>")
            return
        key, _, value = parts[1].partition("=")
        try:
            prefs_store.set_pref(s.current_user, key.strip(), value.strip())
            print(f"set {key.strip()} = {value.strip()} for {s.current_user}")
        except ValueError as e:
            print(f"error: {e}")
        return
    print("usage: /prefs        OR        /prefs set <key>=<value>")


# --- main loop -------------------------------------------------------------


def main() -> int:
    setup_logging(level=logging.INFO)
    session_log = SessionLog()
    session_log.event("session_start", default_user=settings.DEFAULT_USER_ID)

    try:
        bq = BigQueryRunner(project_id=settings.GOOGLE_CLOUD_PROJECT or None)
        schema_summary = get_schema_summary(bq)
        bucket = GoldenBucket.load()
        llm = GeminiLLM()
        graph = build_graph()
        # Make sure all SQLite tables exist.
        reports_store.init_db()
        feedback_store.init_db()
        prefs_store.init_db()
    except Exception as e:  # noqa: BLE001
        print(f"Failed to initialize: {e}", file=sys.stderr)
        traceback.print_exc()
        session_log.event("init_failed", error=str(e))
        return 2

    s = Session(current_user=settings.DEFAULT_USER_ID)
    resources = {
        "bq": bq,
        "golden_bucket": bucket,
        "llm": llm,
        "schema_summary": schema_summary,
        "session": session_log,
    }

    _print_banner(session_log, schema_summary, s.current_user, s.current_role)

    while True:
        try:
            prompt = f"[{s.current_user}] you> "
            if s.pending_action:
                prompt = f"[{s.current_user} CONFIRM] you> "
            user = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue

        if user.lower() in {"/quit", "/exit", ":q"}:
            break

        # Confirmation handling: pending action takes precedence over commands.
        if s.pending_action:
            if _consume_pending(s, user, trace_id=None):
                continue

        # Slash commands
        if user.startswith("/"):
            cmd, _, rest = user[1:].partition(" ")
            cmd = cmd.lower()
            try:
                if cmd in {"help", "h"}:
                    print(HELP)
                elif cmd == "persona":
                    p = load_active_persona()
                    print(f"[{p.name}] {p.description}\n--- instructions ---\n{p.instructions}\n")
                elif cmd == "counters":
                    for k, v in sorted(counters_snapshot().items()):
                        print(f"  {k}: {v}")
                elif cmd == "login":
                    cmd_login(s, rest)
                elif cmd == "whoami":
                    cmd_whoami(s)
                elif cmd == "save":
                    cmd_save(s, rest)
                elif cmd == "reports":
                    cmd_reports(s, rest)
                elif cmd == "show":
                    cmd_show(s, rest)
                elif cmd == "delete":
                    cmd_delete(s, rest)
                elif cmd in {"delete-matching", "delete_matching"}:
                    cmd_delete_matching(s, rest)
                elif cmd == "audit":
                    cmd_audit(s, rest)
                elif cmd == "up":
                    cmd_up_down(s, "up")
                elif cmd == "down":
                    cmd_up_down(s, "down")
                elif cmd == "feedback":
                    cmd_feedback(s)
                elif cmd == "prefs":
                    cmd_prefs(s, rest)
                else:
                    print(f"unknown command: /{cmd}. Type /help for the list.")
            except Exception as e:  # noqa: BLE001
                print(f"command error: {e}")
                logging.exception("CLI command failed")
            continue

        # Treat as natural-language question — invoke the graph.
        trace_id = uuid.uuid4().hex[:10]
        session_log.event("turn_start", trace_id=trace_id, user=s.current_user, user_msg=user)
        initial = {
            "question": user,
            "user_id": s.current_user,
            "trace_id": trace_id,
            "sql_attempts": 0,
            "resources": resources,
        }
        try:
            final = graph.invoke(initial)
        except Exception as e:  # noqa: BLE001
            session_log.event("turn_unhandled_error", trace_id=trace_id, error=str(e))
            print(f"\nagent> Sorry, I hit an unexpected error. trace_id={trace_id}\n")
            logging.exception("unhandled in graph.invoke")
            continue

        msg = final.get("final_message") or "(no output)"
        print(f"\nagent> {msg}\n")
        session_log.event("turn_end", trace_id=trace_id, output_chars=len(msg))

        # Track for /save and /up //down
        s.last_trace_id = trace_id
        s.last_question = user
        # Only stash a real analytical report — refusals shouldn't be saveable.
        if final.get("report"):
            s.last_report = final["report"]

    session_log.event("session_end")
    session_log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
