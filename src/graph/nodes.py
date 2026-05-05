"""LangGraph node implementations.

Every node:
- reads from / writes to the AgentState
- is wrapped by `timed()` so timing + errors hit the session JSONL log
- never raises in normal flow — errors set state["error"] and route via edges
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from src import settings
from src.graph.state import AgentState
from src.obs.log import SessionLog, incr, timed
from src.safety.pii import mask_dataframe, scrub_text
from src.safety.sql_guard import validate_sql
from src.tools.bq import BigQueryRunner, get_schema_summary
from src.tools.golden_bucket import GoldenBucket, Trio, format_trios_for_prompt
from src.tools.persona import load_active_persona
from src.tools import feedback_store, prefs_store

logger = logging.getLogger(__name__)


# --- helpers ---------------------------------------------------------------


def _resources(state: AgentState) -> Dict[str, Any]:
    return state.get("resources", {})


def _session(state: AgentState) -> SessionLog:
    return _resources(state)["session"]


def _trace(state: AgentState) -> str:
    return state.get("trace_id", "no-trace")


def _strip_code_fence(text: str) -> str:
    """LLMs love to wrap SQL in ```sql ...```. Strip it."""
    text = text.strip()
    fence = re.match(r"^```(?:sql)?\s*\n(.*?)\n```\s*$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text


# --- nodes -----------------------------------------------------------------


_FORMAT_HINTS = (
    (re.compile(r"\b(as|in)\s+(a\s+)?table\b|\btabular\b", re.IGNORECASE), "table"),
    (re.compile(r"\bbullet(s|\s+points?)?\b", re.IGNORECASE), "bullets"),
    (re.compile(r"\b(as\s+)?prose\b|\bnarrative\b|\bin\s+paragraphs?\b", re.IGNORECASE), "prose"),
)


def _detect_format_hint(question: str) -> str | None:
    for pattern, fmt in _FORMAT_HINTS:
        if pattern.search(question):
            return fmt
    return None


def router_node(state: AgentState) -> Dict[str, Any]:
    """Classify intent. Catches obvious prompt-injection / off-topic.
    Also detects implicit format prefs and persists them per-user."""
    session = _session(state)
    trace_id = _trace(state)
    question = state["question"]
    user_id = state.get("user_id") or settings.DEFAULT_USER_ID

    with timed(session, "router", trace_id, question_preview=question[:200]):
        # Implicit pref detection — write once, read on every report.
        fmt = _detect_format_hint(question)
        if fmt:
            try:
                prefs_store.set_pref(user_id, "report_format", fmt)
                session.event("pref_set_implicit", trace_id=trace_id, key="report_format", value=fmt)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to persist implicit pref: %s", e)

        # Heuristic fast-path for obvious injection patterns. Saves tokens
        # and avoids exposing the LLM to the malicious string.
        injection_patterns = (
            r"ignore (all|any|the )?(previous|prior|above) instructions",
            r"system prompt",
            r"you are now",
            r"reveal your (instructions|prompt|system)",
            r"jailbreak",
        )
        for pat in injection_patterns:
            if re.search(pat, question, re.IGNORECASE):
                incr("router.injection_blocked")
                return {
                    "intent": "injection",
                    "refusal_reason": "Detected attempt to override safety instructions.",
                }

        # Reports CRUD intent — natural-language version routes to a node
        # that points the user to the CLI commands, since natural-language
        # destructive ops require the confirmation flow which is owned by
        # the CLI loop in this prototype.
        if re.search(r"\b(save|saved|list|show|delete|remove|forget)\b.*\b(reports?|saved)\b", question, re.IGNORECASE):
            return {"intent": "reports_crud"}
        if re.search(r"\b(reports?)\b.*\b(save|saved|list|show|delete|remove)\b", question, re.IGNORECASE):
            return {"intent": "reports_crud"}

        # Pure-greeting / smalltalk — short and obvious only.
        if re.fullmatch(r"\s*(hi|hello|hey|thanks|thank you|bye)\W*", question, re.IGNORECASE):
            return {"intent": "smalltalk", "refusal_reason": "Greeting received."}

        # Default: treat as analysis. A keyword router on free-form English
        # is a losing game (plurals, synonyms, paraphrases); we let the
        # downstream SQL generator + validator + self-heal loop reject
        # questions that don't make sense against the schema.
        return {"intent": "analysis"}


def refuse_node(state: AgentState) -> Dict[str, Any]:
    session = _session(state)
    trace_id = _trace(state)
    intent = state.get("intent")
    reason = state.get("refusal_reason") or "Out of scope."
    with timed(session, "refuse", trace_id, intent=intent):
        if intent == "injection":
            msg = (
                "I can only answer questions about the retail data "
                "(sales, customers, products, orders). I won't change my "
                "instructions or reveal system prompts."
            )
        elif intent == "reports_crud":
            msg = (
                "Saved-report management is available via CLI commands "
                "(safer for destructive ops):\n"
                "  /save <title>           — save the most recent report\n"
                "  /reports                — list your saved reports\n"
                "  /show <id>              — show a saved report\n"
                "  /delete <id>            — delete one report (with confirmation)\n"
                "  /delete-matching <text> — delete all your reports whose title or "
                "body contains <text> (with confirmation)\n"
                "Type /help for the full command list."
            )
        else:
            msg = f"I can only answer retail-data analysis questions. Reason: {reason}"
        incr("refusal.count")
        return {"final_message": msg}


def retrieve_node(state: AgentState) -> Dict[str, Any]:
    session = _session(state)
    trace_id = _trace(state)
    question = state["question"]
    bucket: GoldenBucket = _resources(state)["golden_bucket"]
    with timed(session, "retrieve", trace_id):
        try:
            trios: List[Trio] = bucket.retrieve(question, k=3)
        except Exception as e:  # noqa: BLE001
            logger.warning("Golden Bucket retrieval failed: %s — proceeding with no examples", e)
            trios = []
        session.event(
            "trios_retrieved",
            trace_id=trace_id,
            ids=[t.id for t in trios],
            tags=[t.tags for t in trios],
        )
        return {"retrieved_trios": trios}


_SQL_SYS = """You are a SQL generator for Google BigQuery, working on the public dataset
`bigquery-public-data.thelook_ecommerce`. Available tables: orders, order_items,
products, users.

Rules:
- Output ONLY a single SQL SELECT (or WITH ... SELECT) statement. No prose, no markdown.
- Always fully qualify tables as `bigquery-public-data.thelook_ecommerce.<table>`.
- Exclude line items with status IN ('Cancelled','Returned') for revenue metrics
  unless the user explicitly asks about cancellations/returns.
- Use safe joins (e.g. JOIN ... ON id keys), and prefer ROUND(...,2) for money.
- Add a LIMIT for top-N questions; never produce open-ended SELECT * with no filter.
- If the user requests PII (emails, phones, names), still write the query — the
  application layer masks PII at egress, you do not need to do that here.
"""


def sql_gen_node(state: AgentState) -> Dict[str, Any]:
    session = _session(state)
    trace_id = _trace(state)
    llm = _resources(state)["llm"]
    schema = _resources(state)["schema_summary"]
    trios: List[Trio] = state.get("retrieved_trios", [])

    with timed(session, "sql_gen", trace_id, attempt=state.get("sql_attempts", 0)):
        few_shot = format_trios_for_prompt(trios) if trios else "(none retrieved)"
        prior_sql = state.get("sql")
        prior_err = state.get("sql_error")
        last_kind = state.get("last_failure_kind")

        retry_block = ""
        if prior_sql and prior_err:
            retry_block = (
                "\n--- Previous attempt failed ---\n"
                f"Failure kind: {last_kind}\n"
                f"Previous SQL:\n{prior_sql}\n"
                f"Error/issue:\n{prior_err}\n"
                "Fix the issue and produce a corrected query.\n"
            )
        elif last_kind == "empty":
            retry_block = (
                "\n--- Previous attempt returned 0 rows ---\n"
                "Likely the time window or a filter was too restrictive. "
                "Loosen the date filter (e.g. trailing 12 months instead of "
                "current month) or relax string filters (use LIKE / LOWER).\n"
            )

        user_msg = (
            f"Database schema (compact):\n{schema}\n\n"
            f"Few-shot examples:\n{few_shot}\n"
            f"{retry_block}\n"
            f"User question: {state['question']}\n\n"
            "Return only the SQL."
        )

        try:
            resp = llm.invoke([SystemMessage(content=_SQL_SYS), HumanMessage(content=user_msg)])
            sql = _strip_code_fence(resp.content if hasattr(resp, "content") else str(resp))
            session.event("sql_generated", trace_id=trace_id, sql=sql)
            return {"sql": sql, "sql_attempts": state.get("sql_attempts", 0) + 1, "sql_error": None}
        except Exception as e:  # noqa: BLE001
            logger.error("SQL generation failed: %s", e)
            return {
                "error": f"SQL generation failed: {e}",
                "final_message": "I couldn't generate a SQL query for that question. Please try rephrasing.",
            }


def validate_node(state: AgentState) -> Dict[str, Any]:
    session = _session(state)
    trace_id = _trace(state)
    bq: BigQueryRunner = _resources(state)["bq"]
    sql = state.get("sql") or ""

    with timed(session, "validate", trace_id):
        # 1. Static guard.
        guard = validate_sql(sql)
        if not guard.ok:
            session.event("validate_static_fail", trace_id=trace_id, reason=guard.reason)
            return {
                "sql_error": f"static-guard: {guard.reason}",
                "last_failure_kind": "validate",
            }

        # 2. BigQuery dry-run (free).
        ok, err, bytes_scanned = bq.dry_run_query(sql)
        if not ok:
            session.event("validate_dryrun_fail", trace_id=trace_id, error=err)
            return {
                "sql_error": err,
                "last_failure_kind": "validate",
            }

        session.event("validate_ok", trace_id=trace_id, bytes_scanned=bytes_scanned)
        return {"sql_error": None, "last_failure_kind": None}


def execute_node(state: AgentState) -> Dict[str, Any]:
    session = _session(state)
    trace_id = _trace(state)
    bq: BigQueryRunner = _resources(state)["bq"]
    sql = state["sql"]

    with timed(session, "execute", trace_id):
        try:
            df = bq.execute_query(sql)
        except Exception as e:  # noqa: BLE001
            session.event("execute_fail", trace_id=trace_id, error=str(e))
            return {"sql_error": str(e), "last_failure_kind": "execute"}

        session.event("execute_ok", trace_id=trace_id, rows=len(df), columns=list(df.columns))
        if df.empty:
            return {
                "bq_result_df": df,
                "sql_error": "query returned 0 rows",
                "last_failure_kind": "empty",
            }
        return {"bq_result_df": df, "sql_error": None, "last_failure_kind": None}


def mask_node(state: AgentState) -> Dict[str, Any]:
    session = _session(state)
    trace_id = _trace(state)
    df = state["bq_result_df"]
    with timed(session, "mask", trace_id):
        result = mask_dataframe(df)
        session.event(
            "mask_done",
            trace_id=trace_id,
            masked_columns=result.masked_columns,
            cell_hits=result.cell_hits,
        )
        if result.masked_columns or result.cell_hits:
            incr("pii.records_masked")
        return {
            "masked_df": result.df,
            "pii_masked_columns": result.masked_columns,
            "pii_cell_hits": result.cell_hits,
        }


_REPORT_SYS_TMPL = """You are a retail data analyst writing a report for a non-technical
executive. The data has already been queried and PII has been removed
upstream — you may freely use the values shown.

Persona instructions:
{persona_instructions}

{user_prefs_block}

Hard rules:
- Do NOT invent numbers. Only state what the data shows.
- Do NOT include any email address, phone number, or full personal name.
  (PII has been replaced with opaque tokens like cust_a3f1; treat those as IDs.)
- Note the date window or filter applied if it materially affects the answer.
"""


def report_node(state: AgentState) -> Dict[str, Any]:
    session = _session(state)
    trace_id = _trace(state)
    llm = _resources(state)["llm"]
    df = state["masked_df"]

    with timed(session, "report", trace_id):
        persona = load_active_persona()
        user_id = state.get("user_id") or settings.DEFAULT_USER_ID
        prefs_block = prefs_store.render_for_prompt(user_id)
        # Cap the rows we show the model — agentic reports don't need 1k rows.
        # Using to_string (no extra deps) instead of to_markdown (needs tabulate).
        preview = df.head(50).to_string(index=False)
        sys_msg = _REPORT_SYS_TMPL.format(
            persona_instructions=persona.instructions,
            user_prefs_block=prefs_block or "(no user preferences set)",
        )
        user_msg = (
            f"User question: {state['question']}\n\n"
            f"SQL used:\n{state['sql']}\n\n"
            f"Result rows: {len(df)} (showing up to 50 below)\n\n"
            f"{preview}"
        )
        try:
            resp = llm.invoke([SystemMessage(content=sys_msg), HumanMessage(content=user_msg)])
            text = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:  # noqa: BLE001
            logger.error("Report generation failed: %s", e)
            return {
                "final_message": (
                    f"I ran the query (got {len(df)} rows) but couldn't synthesize the "
                    f"report. SQL was:\n\n```sql\n{state['sql']}\n```"
                )
            }

        # Belt-and-braces PII scrub on the rendered text.
        clean_text, leaks = scrub_text(text)
        if leaks:
            session.event("report_pii_leak_caught", trace_id=trace_id, hits=leaks)

        session.event("report_done", trace_id=trace_id, persona=persona.name, length=len(clean_text))

        # Record this turn for the learning loop.
        try:
            feedback_store.record(
                trace_id=trace_id,
                user_id=user_id,
                question=state["question"],
                sql=state.get("sql") or "",
                report=clean_text,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to record pending trio: %s", e)

        return {"report": clean_text, "final_message": clean_text}


def graceful_fail_node(state: AgentState) -> Dict[str, Any]:
    session = _session(state)
    trace_id = _trace(state)
    with timed(session, "graceful_fail", trace_id):
        # If an upstream node already set a specific message (e.g. LLM
        # provider down), preserve it. Otherwise build a retry summary.
        existing = state.get("final_message")
        if existing:
            incr("graceful_fail.count")
            return {"final_message": existing}
        attempts = state.get("sql_attempts", 0)
        last = state.get("sql_error") or "unknown"
        kind = state.get("last_failure_kind") or "unknown"
        msg = (
            f"I tried {attempts} time(s) but couldn't get a working answer.\n"
            f"Last failure ({kind}): {last}\n"
            f"You can rephrase the question or ask about the schema "
            f"(e.g. 'what columns does the orders table have?')."
        )
        incr("graceful_fail.count")
        return {"final_message": msg}


# --- routing predicates ----------------------------------------------------


def route_after_router(state: AgentState) -> str:
    intent = state.get("intent")
    if intent == "analysis":
        return "retrieve"
    return "refuse"


def route_after_validate(state: AgentState) -> str:
    if state.get("sql_error") is None:
        return "execute"
    if state.get("sql_attempts", 0) >= settings.SQL_RETRY_LIMIT:
        return "graceful_fail"
    return "sql_gen"


def route_after_execute(state: AgentState) -> str:
    if state.get("sql_error") is None:
        return "mask"
    if state.get("sql_attempts", 0) >= settings.SQL_RETRY_LIMIT:
        return "graceful_fail"
    return "sql_gen"


def route_after_sql_gen(state: AgentState) -> str:
    """If sql_gen itself errored out (LLM down even after fallback), give up."""
    if state.get("error"):
        return "graceful_fail"
    return "validate"
