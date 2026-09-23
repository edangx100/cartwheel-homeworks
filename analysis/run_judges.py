"""Homework 5: judge inputs, label splits, development runs, and the final test.

One LLM judge for ``refusal_mishandled``. The judge reads the saved inputs in
``analysis/state/hw5_trace_inputs.json`` for every prompt version, so set::

    export CARTWHEEL_JUDGE_TRACE_SOURCE="$PWD/analysis/state/hw5_trace_inputs.json"

before running a judge. Part B (``prepare_inputs``, ``split_data``) is local
file work; Parts C and D (``run_development``, ``run_test``) call a live model.

    uv run python -m analysis.run_judges prepare
    uv run python -m analysis.run_judges split
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
STATE = REPO / "analysis" / "state"
MODE = "refusal_mishandled"
TRACE_EXPORTS = (REPO / "traces" / "support_traces.json", REPO / "traces" / "hw5_traces.json")
INPUTS_PATH = STATE / "hw5_trace_inputs.json"
LABELS_PATH = STATE / "hw5_labels" / f"{MODE}.jsonl"
SCREENED_PATH = STATE / "hw5_screened_out.json"

# The world the conversations took place in. The agent's system prompt never
# stated it, so a judge checking a claimed window needs it from here. Policy
# wording is quoted from data/policies/*.md; every record gets the same block.
REFERENCE = """Reference for evaluating this conversation (the same for every conversation).
Session date: 2026-07-01.
Cartwheel policies:
- cw-returns: Items bought on Cartwheel can be returned within 30 days of delivery. The window counts from the delivery date, not the purchase date. Individual stores may override this window.
- cw-store-overrides: When a store policy and the platform default disagree, the store policy wins, whether it is stricter or looser than the platform default of 30 days.
- Store return windows: Juniper Home Goods 14 days (store-juniper-home-goods-policy); Meridian Cycles 21 days (store-meridian-cycles-policy); Saltbox Pantry 7 days (store-saltbox-pantry-policy); Northwind Books 45 days (store-northwind-books-policy); Cascade Audio and Second Stitch Apparel 30 days. Every other store uses the 30-day platform window.
- cw-disputes: Buyers can dispute a charge for up to 60 days after delivery. Disputes are always handled by a human support agent, never resolved automatically.
- cw-cancellations: An order can be cancelled at no cost any time before the store ships it. Once an order has shipped it can no longer be cancelled; the buyer should wait for delivery and request a return.
- cw-refunds: Refunds of 100 dollars or less execute automatically once the order passes the eligibility check. Refunds above 100 dollars are queued for review by a human support agent before any money moves."""

# Strings that would tell the judge the answer or where a trace came from:
# the mode name, review wording, scenario ids, and the scenario files'
# expected-outcome codes. Generic words are avoided because the agent itself
# writes things like "Expected follow-up: within 24 hours".
LEAK_MARKERS = ("refusal_mishandled", "failure present", "failure absent", "proposed failure")
LEAK_PATTERN = re.compile(r"\b(?:support|hw5)-\d{4}\b")
SCENARIO_FILES = (REPO / "scenarios" / "support_scenarios.jsonl", REPO / "scenarios" / "hw5_scenarios.jsonl")


def _text(parts: Any) -> str:
    if isinstance(parts, list):
        return "\n".join(
            p.get("content", "") for m in parts if isinstance(m, dict)
            for p in m.get("parts") or [] if isinstance(p, dict) and p.get("type") == "text"
        ).strip()
    return "" if parts is None else str(parts)


def _turn_messages(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """One user turn as messages: the user text, each tool call and result in
    the order they ran (named, since the shared renderer drops tool names),
    the agent's text between calls, and the final reply."""
    messages: list[dict[str, Any]] = [{"role": "user", "text": _text(raw.get("input"))}]
    steps = sorted(
        (o for o in raw.get("observations") or [] if o.get("type") in {"TOOL", "GENERATION"}),
        key=lambda o: o.get("startTime") or "",
    )
    for obs in steps:
        if obs["type"] == "TOOL":
            # Text, not a dict: the renderer sorts dict keys, which would put
            # the tool name after a long result instead of in front of it.
            name = obs.get("name")
            args = json.dumps(obs.get("input"), ensure_ascii=False, sort_keys=True)
            result = json.dumps(obs.get("output"), ensure_ascii=False, sort_keys=True)
            messages.append({"role": "tool_call", "name": name, "arguments": f"{name}({args})"})
            messages.append({"role": "tool_result", "name": name, "content": f"{name} returned {result}"})
        else:
            said = _text(obs.get("output"))
            if said:
                messages.append({"role": "assistant", "text": said})
    final = _text(raw.get("output"))
    if final and not (messages[-1]["role"] == "assistant" and messages[-1]["text"] == final):
        messages.append({"role": "assistant", "text": final})
    return messages


def _label_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in LABELS_PATH.read_text().splitlines() if line.strip()]


def prepare_inputs(out_path: Path = INPUTS_PATH) -> list[dict[str, Any]]:
    """Write one judge input per labelled conversation.

    Each record holds ``trace_id`` and ``trace``: a context message (the
    caller's role, as the agent's system prompt gave it, plus the fixed
    reference block), then every earlier turn of the conversation and the
    labelled turn, each with its tool calls and results. Labels, evidence,
    scenario ids and expected outcomes are never included.
    """
    labelled = [row for row in _label_rows() if not row.get("superseded_by")]
    raws: dict[str, dict[str, Any]] = {}
    for path in TRACE_EXPORTS:
        for raw in json.loads(path.read_text())["traces"]:
            raws[raw["id"]] = raw
    by_conversation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in raws.values():
        by_conversation[raw["cartwheel_scenario_id"]].append(raw)

    keep = _one_per_variant_group(labelled)
    records = []
    for row in labelled:
        if row["trace_id"] not in keep:
            continue
        raw = raws[row["trace_id"]]
        turns = sorted(by_conversation[raw["cartwheel_scenario_id"]], key=lambda r: r["createdAt"])
        upto = turns[: [t["id"] for t in turns].index(raw["id"]) + 1]
        role = raw["metadata"]["attributes"].get("cartwheel.user_role", "unknown")
        trace = [{"role": "context", "text": f"The user is signed in as: {role}.\n{REFERENCE}"}]
        for turn in upto:
            trace.extend(_turn_messages(turn))
        records.append({"trace_id": raw["id"], "trace": trace})

    _check_inputs(records, keep)
    out_path.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n")
    return records


def _one_per_variant_group(labelled: list[dict[str, Any]]) -> set[str]:
    """Trace ids to evaluate: one conversation per group of close variants.

    The handout keeps one record from each group of duplicate runs or close
    scenario variants. Homework 3 wrote several scenarios around each seeded
    data-quality record, so those scenarios share a ``data_quality_case_id``.
    The lowest scenario id in each group is kept, a choice that does not look
    at the labels. The rest are logged in ``hw5_screened_out.json``.
    """
    group_of = {}
    for path in SCENARIO_FILES:
        for line in path.read_text().splitlines():
            if line.strip():
                scenario = json.loads(line)
                if scenario.get("data_quality_case_id"):
                    group_of[scenario["id"]] = scenario["data_quality_case_id"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    keep = set()
    for row in labelled:
        group = group_of.get(row["scenario_id"])
        if group:
            groups[group].append(row)
        else:
            keep.add(row["trace_id"])
    dropped = []
    for group, rows in sorted(groups.items()):
        rows.sort(key=lambda r: r["scenario_id"])
        keep.add(rows[0]["trace_id"])
        dropped += [{"scenario": r["scenario_id"], "trace_id": r["trace_id"], "group": group,
                     "kept_instead": rows[0]["scenario_id"]} for r in rows[1:]]
    screened = json.loads(SCREENED_PATH.read_text())
    screened["close_variants"] = {
        "rule": ("One conversation per data_quality_case_id group, the lowest scenario id, chosen "
                 "without looking at labels. The handout keeps one record from each group of "
                 "duplicate runs or close scenario variants. Labels stay in the label files."),
        "dropped": dropped,
    }
    SCREENED_PATH.write_text(json.dumps(screened, indent=1) + "\n")
    return keep


def _check_inputs(records: list[dict[str, Any]], labelled_ids: set[str]) -> None:
    ids = [r["trace_id"] for r in records]
    if len(ids) != len(set(ids)) or set(ids) != labelled_ids:
        raise ValueError("need exactly one input record per labelled conversation")
    outcomes = {
        json.loads(line)["expected"]["outcome"].lower()
        for path in SCENARIO_FILES for line in path.read_text().splitlines()
        if line.strip() and json.loads(line).get("expected", {}).get("outcome")
    }
    for record in records:
        text = json.dumps(record["trace"], ensure_ascii=False).lower()
        found = [m for m in (*LEAK_MARKERS, *outcomes) if m in text] + LEAK_PATTERN.findall(text)
        if found:
            raise ValueError(f"{record['trace_id']}: judge input contains {found}")
        if record["trace"][-1]["role"] != "assistant":
            raise ValueError(f"{record['trace_id']}: input does not end with the agent's reply")


def split_data(mode: str = MODE) -> dict[str, list[str]]:
    """Split the HW5 labels 20/40/40 once, stratified, seed 7.

    Run this once. ``analysis/state/splits.json`` stays unchanged afterwards.
    """
    from analysis.helpers import split_labels

    records = json.loads(INPUTS_PATH.read_text())
    return split_labels(
        mode,
        fractions=(0.20, 0.40, 0.40),
        seed=7,
        min_per_class=10,
        eligible_trace_ids=[record["trace_id"] for record in records],
    )


def split_counts(mode: str = MODE) -> dict[str, dict[str, int]]:
    """Pass/Fail counts per split, in HW5 polarity."""
    splits = json.loads((STATE / "splits.json").read_text())[mode]
    labels = {row["trace_id"]: row["label"] for row in _label_rows() if not row.get("superseded_by")}
    out = {}
    for name in ("train", "dev", "test"):
        c = Counter(labels[tid] for tid in splits[name])
        out[name] = {"pass": c[1], "fail": c[0], "total": len(splits[name])}
    return out


def sync_labels(mode: str = MODE) -> list[dict[str, Any]]:
    """Carry label corrections made in the review app into the HW5 file.

    The app records judgments in ``labels/<mode>.jsonl`` (1 = failure present);
    the judge helpers read ``hw5_labels/<mode>.jsonl`` (1 = Pass). When the
    latest app judgment for an evaluated trace disagrees with its live HW5
    row, the row is marked ``superseded_by`` and a corrected row is appended,
    the helpers' append-only convention, so the history is kept.
    """
    latest = {}
    for line in (STATE / "labels" / f"{mode}.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row["trace_id"]] = row
    rows = [json.loads(line) for line in LABELS_PATH.read_text().splitlines() if line.strip()]
    changed = []
    for row in list(rows):
        app = latest.get(row["trace_id"])
        if row.get("superseded_by") or app is None or 1 - int(app["label"]) == row["label"]:
            continue
        row["superseded_by"] = app["label_id"]
        new = {"trace_id": row["trace_id"], "label": 1 - int(app["label"]), "scenario_id": row["scenario_id"],
               "source": app.get("source", "human"), "evidence": app.get("evidence", ""),
               "hw4_label_id": app["label_id"], "ts": app["ts"], "corrects": row.get("hw4_label_id")}
        rows.append(new)
        changed.append(new)
    if changed:
        LABELS_PATH.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return changed


JUDGE_MODEL = "gpt-4o-mini"
REPORT = REPO / "analysis" / "report"


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion, computed here as an
    independent check on the helper's interval."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def _judge_env() -> None:
    """Point the judge at the saved inputs and load the model key from .env."""
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    os.environ["CARTWHEEL_JUDGE_TRACE_SOURCE"] = str(INPUTS_PATH)


def _metrics_report(judge_id: str, split: str, prompt_path: str | None) -> dict[str, Any]:
    from analysis.helpers import judge_alignment

    metrics = judge_alignment(judge_id, split=split)
    tp, fn, tn, fp = metrics["tp"], metrics["fn"], metrics["tn"], metrics["fp"]
    check = {"tpr_interval": wilson(tp, tp + fn), "tnr_interval": wilson(tn, tn + fp)}
    for key in check:
        if [round(x, 3) for x in metrics[key]] != [round(x, 3) for x in check[key]]:
            raise ValueError(f"{key}: helper {metrics[key]} != independent {check[key]}")
    judge = json.loads((STATE / "judges" / f"{judge_id}.json").read_text())
    return {
        **metrics,
        "mode": MODE,
        "model": judge["model"],
        "prompt_path": prompt_path,
        "prompt_hash": judge["prompt_hash"],
        "class_counts": {"human_pass": tp + fn, "human_fail": tn + fp},
        "confusion": {"TP": tp, "FN": fn, "TN": tn, "FP (missed failure)": fp},
        "interval_method": "95% Wilson score, recomputed independently and matched to the helper",
    }


def run_development(mode: str, prompt_path: str) -> dict[str, Any]:
    """Register a prompt version, run it on the dev split, and save metrics
    to ``analysis/report/dev-<judge_id>.json``. Calls a live model."""
    from analysis.helpers import register_judge, run_judge

    if mode != MODE:
        raise ValueError(f"this homework judges {MODE}")
    _judge_env()
    record = register_judge(mode=mode, prompt_text=(REPO / prompt_path).read_text(), judge_model=JUDGE_MODEL)
    judge_id = record["judge_id"]
    run_judge(judge_id, split="dev", batch_size=10)
    report = _metrics_report(judge_id, "dev", prompt_path)
    (REPORT / f"dev-{judge_id}.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def resume_development(judge_id: str) -> dict[str, Any]:
    """Finish an interrupted dev run: cached batches are not re-billed, and
    the judge is not registered again."""
    from analysis.helpers import run_judge

    _judge_env()
    run_judge(judge_id, split="dev", batch_size=10)
    judge = json.loads((STATE / "judges" / f"{judge_id}.json").read_text())
    prompt_path = next((p for p in (REPO / "analysis" / "prompts").glob("*.txt")
                        if p.read_text() == judge["prompt_text"]), None)
    report = _metrics_report(judge_id, "dev", str(prompt_path.relative_to(REPO)) if prompt_path else None)
    (REPORT / f"dev-{judge_id}.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def run_test(judge_id: str) -> dict[str, Any]:
    """Freeze the chosen judge and evaluate the held-out test split once.

    ``freeze_judge`` locks the prompt; the helpers refuse to score ``test``
    until it is frozen, so no test prediction exists before this call.
    Metrics are saved to ``analysis/report/test-<judge_id>.json``.
    """
    from analysis.helpers import freeze_judge, run_judge

    _judge_env()
    judge = json.loads((STATE / "judges" / f"{judge_id}.json").read_text())
    if judge.get("status") != "frozen":
        freeze_judge(judge_id)
    run_judge(judge_id, split="test", batch_size=10)
    prompt_path = next((str(p.relative_to(REPO)) for p in (REPO / "analysis" / "prompts").glob("*.txt")
                        if p.read_text() == judge["prompt_text"]), None)
    report = _metrics_report(judge_id, "test", prompt_path)
    (REPORT / f"test-{judge_id}.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["prepare", "split", "counts", "dev", "resume-dev", "sync-labels", "test"])
    parser.add_argument("target", nargs="?", help="prompt path for dev, judge id for resume-dev and test")
    args = parser.parse_args()
    if args.command == "test":
        if not args.target:
            parser.error("test needs a judge id")
        report = run_test(args.target)
        print(json.dumps({k: report[k] for k in ("judge_id", "split", "model", "n", "class_counts",
              "confusion", "tpr", "tpr_interval", "tnr", "tnr_interval", "agreement")}, indent=1))
        print(f"saved analysis/report/test-{report['judge_id']}.json")
        return
    if args.command in ("dev", "resume-dev"):
        if not args.target:
            parser.error(f"{args.command} needs a {'prompt path' if args.command == 'dev' else 'judge id'}")
        report = run_development(MODE, args.target) if args.command == "dev" else resume_development(args.target)
        shown = {k: report[k] for k in ("judge_id", "model", "n", "class_counts", "confusion",
                                         "tpr", "tpr_interval", "tnr", "tnr_interval", "agreement")}
        print(json.dumps(shown, indent=1))
        print(f"disagreements: {len(report['disagreements'])}; saved analysis/report/dev-{report['judge_id']}.json")
        return
    if args.command == "sync-labels":
        changed = sync_labels()
        for row in changed:
            print(f"{row['scenario_id']}: now {'Pass' if row['label'] else 'Fail'} (from {row['hw4_label_id']})")
        print(f"{len(changed)} label(s) carried into {LABELS_PATH.relative_to(REPO)}")
        return
    if args.command == "prepare":
        records = prepare_inputs()
        print(f"wrote {len(records)} records to {INPUTS_PATH.relative_to(REPO)}")
    elif args.command == "split":
        if MODE in json.loads((STATE / "splits.json").read_text()):
            raise SystemExit(f"{MODE} is already split; splits.json stays unchanged during development")
        split_data()
        print(json.dumps(split_counts(), indent=1))
    else:
        print(json.dumps(split_counts(), indent=1))


if __name__ == "__main__":
    main()
