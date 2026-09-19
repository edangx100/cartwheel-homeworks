"""Load Cartwheel traces and regroup them into sessions for human review.

Cartwheel records one Langfuse trace per user turn. The review interface must
show each conversation whole, so this module groups turn traces by
``cartwheel.session_id`` and orders them by timestamp.

Session identifier resolution, in order:

1. ``cartwheel.session_id`` on the trace's root span attributes, or the
   Langfuse ``sessionId`` field. Traces recorded after the server sets the
   attribute carry it directly.
2. ``analysis/state/session_map.json``, a committed map recovered from the
   server's session store (``.sessions.db``). The Module 1 traces predate the
   attribute, so each trace's user message is matched to the stored user
   message with the nearest timestamp. :func:`build_session_map` writes it.
3. Otherwise the trace is shown alone under an ``unmatched:`` session and
   flagged, never merged into another conversation by guesswork.

Trace sources are the live Langfuse project (canonical) or the Module 1 export
``traces/support_traces.json`` when Langfuse is unavailable. Both have the same
shape because the export stores the same API records.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
STATE_DIR = REPO / "analysis" / "state"
DEFAULT_EXPORT = REPO / "traces" / "support_traces.json"
DEFAULT_SCENARIOS = REPO / "scenarios" / "support_scenarios.jsonl"
DEFAULT_SESSIONS_DB = REPO / ".sessions.db"
SESSION_MAP = STATE_DIR / "session_map.json"

ROOT_SPAN = "cartwheel.session_message"
RETRIEVAL_TOOLS = {"search_help_center", "get_policy"}
WRITE_TOOLS = {"issue_refund", "cancel_order", "escalate_to_human"}
# A trace matches a stored user message only when the stored row is this close
# in time. Observed gaps are under one second; reruns are hours apart.
MATCH_WINDOW_SECONDS = 10.0
SESSION_CONTEXT = re.compile(r"## Session context.*?(?=\n## |\Z)", re.S)


# ---------------------------------------------------------------------------
# raw trace access
# ---------------------------------------------------------------------------

def attributes(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the root span attributes from a trace's metadata."""
    metadata = raw.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            return {}
    attrs = metadata.get("attributes", metadata) if isinstance(metadata, dict) else {}
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except json.JSONDecodeError:
            return {}
    return attrs if isinstance(attrs, dict) else {}


def _obs_attributes(obs: dict[str, Any]) -> dict[str, Any]:
    metadata = obs.get("metadata") or {}
    attrs = metadata.get("attributes") if isinstance(metadata, dict) else None
    return attrs if isinstance(attrs, dict) else {}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _message_text(messages: Any) -> str:
    """Join the text parts of OTel GenAI messages (or return a plain string)."""
    if isinstance(messages, str):
        return messages
    if isinstance(messages, dict):
        messages = [messages]
    chunks: list[str] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        for part in message.get("parts") or []:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(str(part.get("content") or ""))
        if isinstance(message.get("content"), str):
            chunks.append(message["content"])
    return "\n".join(chunks)


def load_export(path: Path = DEFAULT_EXPORT) -> list[dict[str, Any]]:
    """Read root traces from a Module 1 JSON export."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = data["traces"] if isinstance(data, dict) else data
    return [r for r in records if r.get("name", ROOT_SPAN) == ROOT_SPAN]


def load_langfuse(limit: int = 5000) -> list[dict[str, Any]]:
    """Fetch full root traces from the live Langfuse project.

    Uses the same list-then-get calls and JSON conversion as the Module 1
    export, so both sources produce identical records.
    """
    from analysis.helpers import langfuse_io
    from scenarios.export_langfuse import _jsonable

    client = langfuse_io._client()
    summaries: list[Any] = []
    page = 1
    while len(summaries) < limit:
        response = client.api.trace.list(page=page, limit=100, name=ROOT_SPAN)
        batch = list(response.data or [])
        summaries.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [_jsonable(client.api.trace.get(s.id)) for s in summaries[:limit]]


def load_traces(source: str, export_path: Path) -> tuple[list[dict[str, Any]], str]:
    """Load raw traces from ``langfuse``, ``export``, or ``auto``.

    ``auto`` prefers Langfuse and falls back to the export, returning a note
    that the interface displays so the fallback is never silent.
    """
    if source in {"langfuse", "auto"}:
        try:
            from analysis.helpers import langfuse_io

            if not langfuse_io.is_configured():
                raise RuntimeError("LANGFUSE_* variables are not set")
            return load_langfuse(), "langfuse"
        except Exception as exc:  # noqa: BLE001 - reported to the reviewer
            if source == "langfuse":
                raise
            note = f"export (Langfuse unavailable: {type(exc).__name__}: {exc})"
            return load_export(export_path), note[:300]
    return load_export(export_path), "export"


# ---------------------------------------------------------------------------
# session identifiers
# ---------------------------------------------------------------------------

def native_session_id(raw: dict[str, Any]) -> str | None:
    """Return the session id recorded on the trace itself, if any."""
    return attributes(raw).get("cartwheel.session_id") or raw.get("sessionId") or None


def build_session_map(
    raws: list[dict[str, Any]], sessions_db: Path = DEFAULT_SESSIONS_DB
) -> dict[str, Any]:
    """Recover ``trace_id -> session_id`` from the server's session store.

    Each trace's user message is compared with the stored user messages; the
    match is the stored row with identical text and the nearest timestamp
    inside :data:`MATCH_WINDOW_SECONDS`. The database is opened read only.
    """
    uri = f"file:{Path(sessions_db).resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    by_text: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    try:
        rows = connection.execute(
            "SELECT session_id, message_data, created_at FROM agent_messages"
        ).fetchall()
    finally:
        connection.close()
    for session_id, message_data, created_at in rows:
        message = json.loads(message_data)
        if message.get("role") != "user":
            continue
        content = message.get("content")
        text = content if isinstance(content, str) else _message_text(content)
        stamp = _parse_time(created_at)
        if stamp is not None:
            by_text[text.strip()].append((session_id, stamp))

    entries: dict[str, Any] = {}
    for raw in raws:
        trace_id = str(raw["id"])
        stamp = _parse_time(raw.get("timestamp"))
        candidates = by_text.get(_message_text(raw.get("input")).strip(), [])
        if stamp is None or not candidates:
            continue
        ranked = sorted(candidates, key=lambda c: abs((c[1] - stamp).total_seconds()))
        gap = abs((ranked[0][1] - stamp).total_seconds())
        if gap > MATCH_WINDOW_SECONDS:
            continue
        runner_up = (
            round(abs((ranked[1][1] - stamp).total_seconds()), 3) if len(ranked) > 1 else None
        )
        entries[trace_id] = {
            "session_id": ranked[0][0],
            "gap_seconds": round(gap, 3),
            "runner_up_gap_seconds": runner_up,
        }

    # A session should never span two scenarios, and a scenario should never
    # span two sessions; report violations rather than hiding them.
    scenario_sessions: dict[str, set[str]] = defaultdict(set)
    session_scenarios: dict[str, set[str]] = defaultdict(set)
    for raw in raws:
        entry = entries.get(str(raw["id"]))
        scenario = attributes(raw).get("cartwheel.scenario_id")
        if entry and scenario:
            scenario_sessions[scenario].add(entry["session_id"])
            session_scenarios[entry["session_id"]].add(scenario)
    return {
        "method": (
            "user message text equality with nearest stored timestamp within "
            f"{MATCH_WINDOW_SECONDS:g}s, from the server session store"
        ),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trace_count": len(raws),
        "matched": len(entries),
        "unmatched": sorted(str(r["id"]) for r in raws if str(r["id"]) not in entries),
        "scenarios_split_across_sessions": sorted(
            s for s, ids in scenario_sessions.items() if len(ids) > 1
        ),
        "sessions_spanning_scenarios": sorted(
            s for s, ids in session_scenarios.items() if len(ids) > 1
        ),
        "traces": entries,
    }


def load_session_map(path: Path = SESSION_MAP) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {tid: e["session_id"] for tid, e in (data.get("traces") or {}).items()}


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------

def load_scenarios(path: Path = DEFAULT_SCENARIOS) -> dict[str, dict[str, Any]]:
    """Scenario tuple and expected outcome keyed by scenario id (if present)."""
    if not Path(path).exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        out[record["id"]] = {
            "group": record.get("scenario_group"),
            "tuple": record.get("tuple") or {},
            "expected": record.get("expected") or {},
        }
    return out


# ---------------------------------------------------------------------------
# turn and session records for the interface
# ---------------------------------------------------------------------------

def _digest(value: Any) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode()).hexdigest()[:10]


def tool_kind(name: str) -> str:
    if name in RETRIEVAL_TOOLS:
        return "retrieval"
    if name in WRITE_TOOLS:
        return "write"
    return "lookup"


def build_turn(raw: dict[str, Any], host: str | None, registry: dict[str, dict]) -> dict:
    """Convert one root trace into the ordered steps the interface renders.

    A step is one model call: its visible text (a preamble when it also calls
    tools) and the tool calls that follow it. The final reply comes from the
    trace output; the last model call's identical text is not repeated.
    ``registry`` collects the shared system prompt and tool schemas once.
    """
    observations = sorted(raw.get("observations") or [], key=lambda o: o.get("startTime") or "")
    steps: list[dict[str, Any]] = []
    system_prompt = session_context = None
    for obs in observations:
        kind = obs.get("type")
        if kind == "GENERATION":
            output = obs.get("output") or []
            parts = [p for m in output if isinstance(m, dict) for p in m.get("parts") or []]
            texts = [str(p.get("content") or "") for p in parts if p.get("type") == "text"]
            calls = [p.get("name") for p in parts if p.get("type") == "tool_call"]
            gen_input = obs.get("input") or {}
            if system_prompt is None and isinstance(gen_input, dict):
                messages = gen_input.get("messages") or []
                if messages and messages[0].get("role") == "system":
                    system_prompt = _message_text([messages[0]])
                    match = SESSION_CONTEXT.search(system_prompt)
                    session_context = match.group(0).strip() if match else ""
                    boilerplate = SESSION_CONTEXT.sub("{{SESSION CONTEXT}}\n\n", system_prompt)
                    key = "prompt-" + _digest(boilerplate)
                    registry.setdefault(key, {"kind": "system_prompt", "text": boilerplate})
                    schemas = gen_input.get("tools")
                    if schemas:
                        tkey = "tools-" + _digest(schemas)
                        registry.setdefault(tkey, {"kind": "tool_schemas", "value": schemas})
                        system_prompt = (key, tkey)
                    else:
                        system_prompt = (key, None)
            steps.append(
                {
                    "observation_id": obs.get("id"),
                    "model": obs.get("model"),
                    "tokens": obs.get("totalTokens"),
                    "finish": _obs_attributes(obs).get("gen_ai.response.finish_reasons"),
                    "level": obs.get("level"),
                    "status_message": obs.get("statusMessage"),
                    "text": "\n\n".join(t for t in texts if t),
                    "called": calls,
                    "tools": [],
                }
            )
        elif kind == "TOOL":
            attrs = _obs_attributes(obs)
            result = obs.get("output")
            record = {
                "observation_id": obs.get("id"),
                "name": obs.get("name"),
                "kind": tool_kind(str(obs.get("name"))),
                "args": obs.get("input"),
                "result": result,
                "ok": result.get("ok") if isinstance(result, dict) else None,
                "permission_denied": str(attrs.get("cartwheel.permission_denied")) == "true",
                "level": obs.get("level"),
                "status_message": obs.get("statusMessage"),
            }
            if not steps:
                steps.append({"text": "", "called": [], "tools": [], "orphan": True})
            steps[-1]["tools"].append(record)

    reply = _message_text(raw.get("output"))
    final_meta = None
    if steps and not steps[-1]["tools"] and steps[-1]["text"].strip() == reply.strip():
        final_meta = steps.pop()
    prompt_key, tools_key = system_prompt if isinstance(system_prompt, tuple) else (None, None)
    attrs = attributes(raw)
    tools = [t for s in steps for t in s["tools"]]
    html_path = raw.get("htmlPath")
    return {
        "trace_id": str(raw["id"]),
        "timestamp": raw.get("timestamp"),
        "latency": raw.get("latency"),
        "cost": raw.get("totalCost"),
        "langfuse_url": (host.rstrip("/") + html_path) if host and html_path else None,
        "prompt_version": attrs.get("cartwheel.prompt_version"),
        "user": _message_text(raw.get("input")),
        "reply": reply,
        "reply_meta": final_meta,
        "steps": steps,
        "session_context": session_context,
        "prompt_key": prompt_key,
        "tools_key": tools_key,
        "tool_names": [t["name"] for t in tools],
        "flags": {
            "permission_denied": any(t["permission_denied"] for t in tools),
            "tool_error": any(t["ok"] is False for t in tools),
            "write": any(t["kind"] == "write" for t in tools),
            "no_reply": not reply.strip(),
        },
    }


def _store_id(context: str | None) -> str | None:
    match = re.search(r"Store id:\s*([^\n]+)", context or "")
    return match.group(1).strip() if match else None


def build_sessions(
    raws: list[dict[str, Any]],
    session_map: dict[str, str],
    scenarios: dict[str, dict[str, Any]],
    host: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Group turn traces by session and order each session chronologically."""
    registry: dict[str, dict] = {}
    grouped: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    sources: dict[str, str] = {}
    for raw in raws:
        trace_id = str(raw["id"])
        native = native_session_id(raw)
        if native:
            session_id, source = str(native), "attribute"
        elif trace_id in session_map:
            session_id, source = session_map[trace_id], "recovered"
        else:
            session_id, source = f"unmatched:{trace_id}", "unmatched"
        grouped[session_id].append((raw, build_turn(raw, host, registry)))
        # A session is only as trustworthy as its weakest trace link.
        rank = {"attribute": 0, "recovered": 1, "unmatched": 2}
        if rank[source] >= rank.get(sources.get(session_id, "attribute"), 0):
            sources[session_id] = source

    sessions: list[dict[str, Any]] = []
    for session_id, pairs in grouped.items():
        pairs.sort(key=lambda p: p[1]["timestamp"] or "")
        first_attrs = attributes(pairs[0][0])
        scenario_id = first_attrs.get("cartwheel.scenario_id")
        scenario = scenarios.get(scenario_id or "", {})
        turns = [turn for _, turn in pairs]
        for index, turn in enumerate(turns, start=1):
            turn["turn"] = index
        sessions.append(
            {
                "session_id": session_id,
                "session_source": sources[session_id],
                "scenario_id": scenario_id,
                "role": first_attrs.get("cartwheel.user_role"),
                "user_id": first_attrs.get("cartwheel.user_id"),
                "store_id": _store_id(turns[0].get("session_context")),
                "started": turns[0]["timestamp"],
                "scenario": scenario,
                "turns": turns,
                "tool_calls": sum(len(t["tool_names"]) for t in turns),
                "flags": [],
            }
        )

    _flag_outliers(sessions)
    sessions.sort(key=lambda s: s["started"] or "")
    meta = {
        "trace_count": len(raws),
        "session_count": len(sessions),
        "session_sources": {
            key: sum(1 for s in sessions if s["session_source"] == key)
            for key in ("attribute", "recovered", "unmatched")
        },
        "registry": registry,
        "langfuse_host": host,
    }
    return sessions, meta


def _flag_outliers(sessions: list[dict[str, Any]]) -> None:
    """Flag sessions in the top decile for turns or tool calls (header only)."""
    for field, label in (("turns", "turns"), ("tool_calls", "tool calls")):
        values = sorted(
            len(s["turns"]) if field == "turns" else s["tool_calls"] for s in sessions
        )
        if not values:
            continue
        for session in sessions:
            value = len(session["turns"]) if field == "turns" else session["tool_calls"]
            below = sum(v < value for v in values)
            share = below / len(values)
            if share >= 0.9 and value > values[len(values) // 2]:
                session["flags"].append(f"{value} {label} (more than {share:.0%})")


def langfuse_host() -> str | None:
    return os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL")


def main() -> None:
    """Rebuild ``analysis/state/session_map.json`` from the session store."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--sessions-db", type=Path, default=DEFAULT_SESSIONS_DB)
    parser.add_argument("--out", type=Path, default=SESSION_MAP)
    args = parser.parse_args()
    result = build_session_map(load_export(args.export), args.sessions_db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"matched {result['matched']}/{result['trace_count']} traces; "
        f"split scenarios {len(result['scenarios_split_across_sessions'])}; "
        f"sessions spanning scenarios {len(result['sessions_spanning_scenarios'])}; "
        f"wrote {args.out}"
    )


if __name__ == "__main__":
    main()
