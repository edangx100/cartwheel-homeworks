"""Build the Homework 4 review sample in ``analysis/state/sample_manifest.json``.

The handout's four batches, each drawn from traces not already in the sample:

    uniform    --batch initial_uniform --n 15   uniform random traces
    cluster    --batch initial_cluster --n 15   traces nearest k-means centroids
    dimension  --field role --n 30              equal share per value of one
                                                product dimension, chosen before
                                                looking at outcomes
    add        --batch depth --ids ... --reason "..."
                                                traces found by depth searches
    uniform    --batch final_uniform --n 15     stability check after the draft
                                                taxonomy

The unit of review is one trace (one user turn). The interface still shows the
whole session around it. A trace can belong to one batch only.

    uv run python -m analysis.review_app.sample uniform --batch initial_uniform --n 15
"""

from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analysis.helpers.selection import _kmeans, _standardize
from analysis.review_app import server, traces as trace_store

MANIFEST = server.STATE_FILES["/api/manifest"][0]
BATCHES = {
    "initial_uniform": (15, "uniform random sample"),
    "initial_cluster": (15, "k-means cluster representatives"),
    "dimension": (30, "stratified across one product dimension"),
    "depth": (25, "depth searches for candidate modes and close negatives"),
    "final_uniform": (15, "uniform random stability check"),
}
DIMENSIONS = (
    "role", "intent", "record_state", "applicable_policy", "tools_needed",
    "difficulty", "user_style",
)


def load_pool(
    source: str, export: Path, scenarios: Path, all_traces: bool = False
) -> list[dict[str, Any]]:
    """One row per trace with its session, dimensions, and cluster features.

    Limited to the HW3 export (the final run) unless ``all_traces`` is set.
    """
    raws, _ = trace_store.load_traces(source, export)
    if not all_traces:
        raws, _ = trace_store.restrict_to_export(raws, export)
    sessions, _ = trace_store.build_sessions(
        raws, trace_store.load_session_map(), trace_store.load_scenarios(scenarios)
    )
    rows = []
    for session in sessions:
        dims = {"role": session["role"], **(session["scenario"].get("tuple") or {})}
        for turn in session["turns"]:
            kinds = [t["kind"] for s in turn["steps"] for t in s["tools"]]
            rows.append(
                {
                    "trace_id": turn["trace_id"],
                    "session_id": session["session_id"],
                    "dims": {k: dims.get(k) for k in DIMENSIONS},
                    "features": [
                        len(kinds),
                        len(set(turn["tool_names"])),
                        kinds.count("retrieval"),
                        kinds.count("write"),
                        int(turn["flags"]["permission_denied"]),
                        int(turn["flags"]["tool_error"]),
                        turn["turn"],
                        len(session["turns"]),
                        math.log1p(len(turn["reply"])),
                        *(int(session["role"] == r) for r in ("shopper", "merchant", "support")),
                    ],
                }
            )
    return rows


def read_manifest() -> dict[str, Any]:
    manifest = server.read_json(MANIFEST, {"batches": {}, "items": []})
    for name, (target, method) in BATCHES.items():
        manifest["batches"].setdefault(name, {"target": target, "method": method})
    return manifest


def pick_uniform(pool: list[dict], n: int, seed: int) -> list[tuple[dict, str]]:
    chosen = random.Random(seed).sample(pool, min(n, len(pool)))
    return [(row, f"uniform random (seed {seed})") for row in chosen]


def pick_cluster(pool: list[dict], n: int, seed: int, k: int) -> list[tuple[dict, str]]:
    """Take the traces nearest each centroid, cycling through clusters."""
    vectors = _standardize([row["features"] for row in pool])
    assign = _kmeans(vectors, k=k, seed=seed)
    members: dict[int, list[int]] = defaultdict(list)
    for index, cluster in enumerate(assign):
        members[cluster].append(index)
    ranked: dict[int, list[int]] = {}
    for cluster, indexes in members.items():
        centroid = [sum(vectors[i][d] for i in indexes) / len(indexes) for d in range(len(vectors[0]))]
        ranked[cluster] = sorted(
            indexes, key=lambda i: sum((a - b) ** 2 for a, b in zip(vectors[i], centroid))
        )
    picks: list[tuple[dict, str]] = []
    depth = 0
    while len(picks) < n and any(len(v) > depth for v in ranked.values()):
        for cluster in sorted(ranked, key=lambda c: -len(members[c])):
            if len(picks) < n and len(ranked[cluster]) > depth:
                row = pool[ranked[cluster][depth]]
                picks.append(
                    (row, f"cluster {cluster} of {k} ({len(members[cluster])} traces), rank {depth + 1}")
                )
        depth += 1
    return picks


def pick_dimension(pool: list[dict], field: str, n: int, seed: int) -> list[tuple[dict, str]]:
    """Spread ``n`` picks evenly across the values of one dimension."""
    by_value: dict[str, list[dict]] = defaultdict(list)
    for row in pool:
        by_value[str(row["dims"].get(field))].append(row)
    rng = random.Random(seed)
    for rows in by_value.values():
        rng.shuffle(rows)
    values = sorted(by_value)
    picks: list[tuple[dict, str]] = []
    depth = 0
    while len(picks) < n and any(len(by_value[v]) > depth for v in values):
        for value in values:
            if len(picks) < n and len(by_value[value]) > depth:
                picks.append((by_value[value][depth], f"{field}={value}"))
        depth += 1
    return picks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["uniform", "cluster", "dimension", "add", "status"])
    parser.add_argument("--batch", choices=sorted(BATCHES))
    parser.add_argument("--n", type=int)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--clusters", type=int, default=8)
    parser.add_argument("--field", choices=DIMENSIONS)
    parser.add_argument("--ids", nargs="*", default=[])
    parser.add_argument("--reason", default="")
    parser.add_argument("--source", choices=["auto", "langfuse", "export"], default="auto")
    parser.add_argument("--export", type=Path, default=trace_store.DEFAULT_EXPORT)
    parser.add_argument("--scenarios", type=Path, default=trace_store.DEFAULT_SCENARIOS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all-traces", action="store_true",
                        help="include Langfuse traces outside the HW3 export")
    args = parser.parse_args()

    manifest = read_manifest()
    if args.command == "status":
        for name, info in manifest["batches"].items():
            count = sum(1 for item in manifest["items"] if item["batch"] == name)
            print(f"{name:16} {count:3}/{info['target']}  {info['method']}")
        print(f"total distinct traces: {len({i['trace_id'] for i in manifest['items']})}")
        return

    batch = args.batch or {"dimension": "dimension", "add": "depth"}.get(args.command)
    if batch is None:
        parser.error("--batch is required")
    from dotenv import load_dotenv

    load_dotenv(trace_store.REPO / ".env")
    taken = {item["trace_id"] for item in manifest["items"]}
    # Traces already coded outside the batches (the Part A review) are not redrawn.
    annotations = server.read_json(*server.STATE_FILES["/api/annotations"]).get("annotations", [])
    taken |= {a["trace_id"] for a in annotations if a.get("batch") == "part_a"}
    pool = [
        row for row in load_pool(args.source, args.export, args.scenarios, args.all_traces)
        if row["trace_id"] not in taken
    ]
    n = args.n or (BATCHES[batch][0] - sum(1 for i in manifest["items"] if i["batch"] == batch))

    if args.command == "uniform":
        picks = pick_uniform(pool, n, args.seed)
    elif args.command == "cluster":
        picks = pick_cluster(pool, n, args.seed, args.clusters)
    elif args.command == "dimension":
        if not args.field:
            parser.error("--field is required for dimension")
        manifest["batches"][batch]["field"] = args.field
        picks = pick_dimension(pool, args.field, n, args.seed)
    else:
        by_id = {row["trace_id"]: row for row in pool}
        missing = [tid for tid in args.ids if tid not in by_id]
        if missing:
            parser.error(f"unknown or already sampled traces: {', '.join(missing)}")
        if not args.reason:
            parser.error("--reason is required for add (e.g. the search that found the traces)")
        picks = [(by_id[tid], args.reason) for tid in args.ids]

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_items = [
        {
            "trace_id": row["trace_id"],
            "session_id": row["session_id"],
            "batch": batch,
            "reason": reason,
            "dims": row["dims"],
            "added_at": stamp,
        }
        for row, reason in picks
    ]
    for item in new_items:
        print(f"{item['batch']:16} {item['trace_id']}  {item['reason']}")
    if args.dry_run:
        print(f"dry run: {len(new_items)} traces not written")
        return
    manifest["items"].extend(new_items)
    server.write_json(MANIFEST, manifest)
    print(f"added {len(new_items)} traces to {MANIFEST}")


if __name__ == "__main__":
    main()
