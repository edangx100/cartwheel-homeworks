"""Homework 7: monitor one failure mode with the frozen Homework 5 judge.

One run covers one window of Langfuse traces. It builds one conversation
record per conversation, samples a uniform random share (the only input to
the failure-rate estimate) plus every conversation in the configured risk
groups (inspection only), judges the union once, corrects the random-sample
rate for judge error, and writes the scores back to Langfuse.

    uv run python -m monitoring.run --period before [--dry-run]
    uv run python -m monitoring.run --last-hours 24

A ``--period`` run compares fixed scenario runs: every scenario in
``scenarios/monitoring_scenarios.jsonl`` must be present, each with one trace
per turn, and every model call must use the configured Cartwheel model.
A ``--last-hours`` run groups the window's traces by ``meta.session_id``.

The judge text follows Homework 5 exactly (``analysis/run_judges.py``): a
context message with the caller's role and the fixed reference block, then
each turn's user text, named tool calls and results, and the agent's replies.
Scenario ids, expected outcomes and labels never reach the judge.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from analysis.helpers.normalization import normalize_trace
from analysis.run_judges import LEAK_MARKERS, LEAK_PATTERN, REFERENCE, SCENARIO_FILES, _turn_messages
from monitoring.sample import DEFAULT_RISK_GROUPS, select_traces
from scenarios.export_langfuse import _jsonable

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "monitoring" / "config.json"
SCENARIOS_PATH = REPO / "scenarios" / "monitoring_scenarios.jsonl"
HISTORY_PATH = REPO / "monitoring" / "history.jsonl"
CHART_PATH = REPO / "monitoring" / "prevalence.svg"
# Per-run output with conversation text; gitignored, uploaded by the workflow.
OUTPUT_DIR = REPO / "monitoring" / "output"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    unknown = set(config["risk_groups"]) - set(DEFAULT_RISK_GROUPS)
    if unknown:
        raise ValueError(f"unknown risk groups {sorted(unknown)}")
    return config


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _attributes(trace: dict[str, Any]) -> dict[str, Any]:
    metadata = trace.get("metadata") or {}
    return metadata.get("attributes") or {}


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def fetch_window(start: datetime, end: datetime, keep) -> list[dict[str, Any]]:
    """Full Langfuse traces in [start, end) whose metadata passes ``keep``.

    List responses omit observations, so each kept trace is fetched in full
    and converted to the same JSON shape the Homework 3 export used.
    """
    from dotenv import load_dotenv

    from analysis.helpers import langfuse_io

    load_dotenv(REPO / ".env")
    if not langfuse_io.is_configured():
        raise langfuse_io.LangfuseNotConfigured(
            "set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HOST"
        )
    from langfuse import Langfuse

    client = Langfuse()
    summaries: list[Any] = []
    page = 1
    while True:
        response = client.api.trace.list(
            from_timestamp=start, to_timestamp=end, page=page, limit=100
        )
        batch = list(response.data or [])
        summaries.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    kept = [s for s in summaries if keep((s.metadata or {}).get("attributes") or {})]
    return [_jsonable(client.api.trace.get(s.id)) for s in kept]


# ---------------------------------------------------------------------------
# validate and build conversation records
# ---------------------------------------------------------------------------


def generation_models(trace: dict[str, Any]) -> set[str]:
    return {
        str(o.get("model"))
        for o in trace.get("observations") or []
        if o.get("type") == "GENERATION"
    }


def check_models(traces: list[dict[str, Any]], model: str) -> None:
    """Every model call must be the configured model or a dated snapshot of it."""
    allowed = re.compile(rf"^{re.escape(model)}(-\d{{4}}-\d{{2}}-\d{{2}})?$")
    for trace in traces:
        models = generation_models(trace)
        if not models:
            raise ValueError(f"trace {trace['id']} has no model call")
        wrong = sorted(m for m in models if not allowed.match(m))
        if wrong:
            raise ValueError(f"trace {trace['id']} uses {wrong}, not {model}")


def check_period(traces: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> None:
    """All scenarios present, one trace per turn, and one session each, so a
    period is one complete run with no separate retries mixed in."""
    turns = {s["id"]: 1 + len(s.get("followups") or []) for s in scenarios}
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        by_scenario[_attributes(trace)["cartwheel.scenario_id"]].append(trace)
    missing = sorted(set(turns) - set(by_scenario))
    if missing:
        raise ValueError(f"period is missing {len(missing)} scenario ids: {missing[:5]}")
    wrong = sorted(sid for sid, rows in by_scenario.items() if len(rows) != turns[sid])
    if wrong:
        raise ValueError(f"trace count differs from turn count (retries?) for {wrong[:5]}")
    for sid, rows in by_scenario.items():
        sessions = {_attributes(r).get("cartwheel.session_id") for r in rows} - {None}
        if len(sessions) > 1:
            raise ValueError(f"{sid} spans {len(sessions)} sessions (retries?)")


def _check_text(record_id: str, messages: list[dict[str, Any]]) -> None:
    """The Homework 5 input checks: no mode name, review wording, scenario id
    or expected-outcome code, and the input ends with the agent's reply."""
    outcomes = {
        json.loads(line)["expected"]["outcome"].lower()
        for path in SCENARIO_FILES
        for line in path.read_text().splitlines()
        if line.strip() and json.loads(line).get("expected", {}).get("outcome")
    }
    text = json.dumps(messages, ensure_ascii=False).lower()
    found = [m for m in (*LEAK_MARKERS, *outcomes) if m in text] + LEAK_PATTERN.findall(text)
    if found:
        raise ValueError(f"{record_id}: judge input contains {found}")
    if messages[-1]["role"] != "assistant":
        raise ValueError(f"{record_id}: input does not end with the agent's reply")


def build_conversations(
    traces: list[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    """One record per conversation, grouped on the ``key`` attribute.

    The record id is the final trace id so Langfuse can receive the score.
    Tools and turn count come from the trace evidence; the risk groups read
    them. ``text`` is the Homework 5 judge input for the whole conversation.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        groups[str(_attributes(trace)[key])].append(trace)
    records = []
    for group_key in sorted(groups):
        turns = sorted(groups[group_key], key=lambda t: t.get("createdAt") or t["timestamp"])
        role = _attributes(turns[-1]).get("cartwheel.user_role", "unknown")
        messages = [{"role": "context", "text": f"The user is signed in as: {role}.\n{REFERENCE}"}]
        for turn in turns:
            messages.extend(_turn_messages(turn))
        final_id = str(turns[-1]["id"])
        _check_text(final_id, messages)
        records.append(
            {
                "id": final_id,
                "group_key": group_key,
                "trace_ids": [str(t["id"]) for t in turns],
                "tools": sorted(
                    {
                        str(o.get("name"))
                        for t in turns
                        for o in t.get("observations") or []
                        if o.get("type") == "TOOL"
                    }
                ),
                "turn_count": len(turns),
                "timestamp": turns[-1]["timestamp"],
                "text": normalize_trace({"trace_id": final_id, "trace": messages})["text"],
            }
        )
    return records


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def update_history(record: dict[str, Any], path: Path = HISTORY_PATH) -> list[dict[str, Any]]:
    """One line per period label; a rerun replaces that period's line."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    rows = [row for row in rows if row["label"] != record["label"]] + [record]
    order = {p["label"]: i for i, p in enumerate(load_config()["periods"])}
    rows.sort(key=lambda row: order.get(row["label"], len(order)))
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return rows


def run(
    config: dict[str, Any],
    label: str,
    start: datetime,
    end: datetime,
    *,
    scheduled: bool,
    dry_run: bool,
) -> dict[str, Any]:
    if scheduled:
        traces = fetch_window(start, end, lambda attrs: bool(attrs.get("cartwheel.session_id")))
        # A configured period is already scored under its own label; judging
        # it again would overwrite its per-trace verdicts with a new sample.
        periods = [(_parse_time(p["from"]), _parse_time(p["to"])) for p in config["periods"]]
        traces = [t for t in traces
                  if not any(a <= _parse_time(t["timestamp"]) < b for a, b in periods)]
        check_models(traces, config["model"])
        conversations = build_conversations(traces, "cartwheel.session_id")
    else:
        scenarios = [json.loads(line) for line in SCENARIOS_PATH.read_text().splitlines() if line.strip()]
        ids = {s["id"] for s in scenarios}
        traces = fetch_window(start, end, lambda attrs: attrs.get("cartwheel.scenario_id") in ids)
        check_period(traces, scenarios)
        check_models(traces, config["model"])
        conversations = build_conversations(traces, "cartwheel.scenario_id")
        if len(conversations) != len(scenarios):
            raise ValueError(f"expected {len(scenarios)} conversations, built {len(conversations)}")

    summary: dict[str, Any] = {
        "label": label,
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": end.isoformat().replace("+00:00", "Z"),
        "judge_id": config["judge_id"],
        "model": config["model"],
        "trace_count": len(traces),
        "conversation_count": len(conversations),
    }
    print(f"{label}: {len(traces)} Langfuse traces, {len(conversations)} conversations")
    if not conversations:
        summary.update(random_count=0, risk_count=0, judge_calls=0)
        _write_json(OUTPUT_DIR / f"{label}.json", summary)
        print("no eligible conversations; the judge was not called")
        return summary

    groups = {name: DEFAULT_RISK_GROUPS[name] for name in config["risk_groups"]}
    plan = select_traces(conversations, config["random_rate"], groups, seed=7)
    random_ids = [c["id"] for c in plan["random"]]
    risk_ids = list(dict.fromkeys(c["id"] for members in plan["risk_groups"].values() for c in members))
    summary.update(random_count=len(random_ids), risk_count=len(risk_ids), judge_calls=len(plan["to_judge"]))
    print(f"random sample: {len(random_ids)} conversations (estimates the failure rate)")
    for name, members in plan["risk_groups"].items():
        print(f"risk group {name}: {len(members)} conversations (inspection only)")
    print(f"judge calls: {len(plan['to_judge'])} to {config['judge_id']} (union, each judged once)")

    output = {
        **summary,
        "random_ids": random_ids,
        "risk_groups": {name: [c["id"] for c in members] for name, members in plan["risk_groups"].items()},
        "conversations": [{k: c[k] for k in ("id", "group_key", "trace_ids", "tools", "turn_count", "timestamp")} for c in conversations],
    }
    if dry_run:
        _write_json(OUTPUT_DIR / f"{label}-plan.json", output)
        print("dry run: the judge was not called")
        return summary

    from monitoring.correct import corrected_mode_prevalence
    from monitoring.run_judges import judge_sample, judge_test_data
    from monitoring.write_scores import build_score_records, post_scores

    verdicts = judge_sample(config["judge_id"], [{"id": c["id"], "text": c["text"]} for c in plan["to_judge"]])
    random_verdicts = {tid: verdicts[tid] for tid in random_ids}
    risk_verdicts = {tid: verdicts[tid] for tid in risk_ids}
    test_labels, test_preds = judge_test_data(config["judge_id"])
    estimate = corrected_mode_prevalence(list(random_verdicts.values()), test_labels, test_preds)
    records = build_score_records(config["judge_mode"], random_verdicts, risk_verdicts, estimate, label)
    # Date each score by the conversations it describes, not by when it was
    # written, so a dashboard over time shows each period at its own date.
    when = {c["id"]: c["timestamp"] for c in conversations}
    for record in records:
        record["timestamp"] = when.get(record["trace_id"], summary["to"])
    written = post_scores(records)
    print(f"raw {estimate['raw']}, corrected {estimate['corrected']} "
          f"[{estimate['ci_low']}, {estimate['ci_high']}]; {written} scores written")

    history = {
        **summary,
        **{k: estimate[k] for k in ("raw", "corrected", "ci_low", "ci_high", "confidence",
                                   "failure_sensitivity", "pass_specificity")},
        "threshold": config["threshold"],
    }
    _write_json(OUTPUT_DIR / f"{label}.json",
                {**output, "random_verdicts": random_verdicts, "risk_verdicts": risk_verdicts,
                 "estimate": estimate, "score_ids": [r["score_id"] for r in records]})
    return history


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    window = parser.add_mutually_exclusive_group(required=True)
    window.add_argument("--period", help="a period label from monitoring/config.json")
    window.add_argument("--last-hours", type=float, help="monitor the traces of the last N hours")
    parser.add_argument("--dry-run", action="store_true", help="sample and count, but do not call the judge")
    args = parser.parse_args(argv)

    config = load_config()
    if args.period:
        period = next((p for p in config["periods"] if p["label"] == args.period), None)
        if period is None:
            parser.error(f"no period {args.period!r} in {CONFIG_PATH.relative_to(REPO)}")
        result = run(config, period["label"], _parse_time(period["from"]), _parse_time(period["to"]),
                     scheduled=False, dry_run=args.dry_run)
        if not args.dry_run:
            from monitoring.chart import prevalence_chart

            rows = update_history(result)
            CHART_PATH.write_text(prevalence_chart(rows, config["threshold"], config["judge_mode"]))
            print(f"updated {HISTORY_PATH.relative_to(REPO)} and {CHART_PATH.relative_to(REPO)}")
    else:
        end = datetime.now(timezone.utc).replace(microsecond=0)
        start = end - timedelta(hours=args.last_hours)
        label = f"last{args.last_hours:g}h-{end.strftime('%Y%m%dT%H%MZ')}"
        run(config, label, start, end, scheduled=True, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
