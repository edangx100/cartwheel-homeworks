"""Offline tests for the Homework 4 review interface backend."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.review_app import server, traces


def _raw(trace_id: str, ts: str, user: str, reply: str, *, scenario: str = "s-1", session=None,
         tools: list[tuple[str, dict, dict]] | None = None) -> dict:
    """A root trace shaped like the Module 1 Langfuse export."""
    attrs = {"cartwheel.scenario_id": scenario, "cartwheel.user_role": "shopper",
             "cartwheel.user_id": "7", "cartwheel.prompt_version": "p1"}
    if session:
        attrs["cartwheel.session_id"] = session
    system = {"role": "system", "parts": [{"type": "text", "content":
              "You are Cartwheel.\n\n## Session context (injected)\n- User role: shopper\n- Store id: none\n\n## Rules\nBe exact."}]}
    obs, clock = [], 0

    def stamp() -> str:
        nonlocal clock
        clock += 1
        return f"{ts[:-1]}{clock:03d}Z" if ts.endswith("Z") else ts

    for name, args, result in tools or []:
        obs.append({"id": f"g{clock}", "type": "GENERATION", "name": "openai.response", "startTime": stamp(),
                    "input": {"messages": [system], "tools": [{"name": name}]}, "model": "m",
                    "output": [{"role": "assistant", "parts": [{"type": "text", "content": f"I'll call {name}."}]},
                               {"role": "assistant", "parts": [{"type": "tool_call", "name": name, "arguments": args}]}]})
        obs.append({"id": f"t{clock}", "type": "TOOL", "name": name, "startTime": stamp(), "input": args,
                    "output": result, "metadata": {"attributes": {"cartwheel.permission_denied": "false"}}})
    obs.append({"id": f"g{clock}", "type": "GENERATION", "name": "openai.response", "startTime": stamp(),
                "input": {"messages": [system]}, "model": "m",
                "output": [{"role": "assistant", "parts": [{"type": "text", "content": reply}]}]})
    return {"id": trace_id, "name": traces.ROOT_SPAN, "timestamp": ts, "metadata": {"attributes": attrs},
            "input": [{"role": "user", "parts": [{"type": "text", "content": user}]}],
            "output": [{"role": "assistant", "parts": [{"type": "text", "content": reply}]}],
            "observations": obs, "htmlPath": f"/project/p/traces/{trace_id}"}


def _sessions_db(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE agent_messages (id INTEGER PRIMARY KEY, session_id TEXT, message_data TEXT, created_at TIMESTAMP)")
    con.executemany("INSERT INTO agent_messages (session_id, message_data, created_at) VALUES (?, ?, ?)",
                    [(sid, json.dumps({"role": "user", "content": text}), at) for sid, text, at in rows])
    con.commit()
    con.close()
    return path


def test_turn_steps_pair_narration_with_tools_and_keep_reply_once() -> None:
    raw = _raw("a" * 32, "2026-09-14T07:00:00Z", "refund 4963", "Refund issued.",
               tools=[("get_order", {"order_id": 4963}, {"ok": True}),
                      ("issue_refund", {"order_id": 4963}, {"ok": True, "status": "queued_for_approval"})])
    registry: dict = {}
    turn = traces.build_turn(raw, "http://lf", registry)
    assert [s["text"] for s in turn["steps"]] == ["I'll call get_order.", "I'll call issue_refund."]
    assert [t["kind"] for s in turn["steps"] for t in s["tools"]] == ["lookup", "write"]
    assert turn["reply"] == "Refund issued." and turn["reply_meta"] is not None
    assert turn["session_context"].startswith("## Session context")
    assert "{{SESSION CONTEXT}}" in registry[turn["prompt_key"]]["text"]
    assert turn["langfuse_url"] == "http://lf/project/p/traces/" + "a" * 32


def test_tool_result_pairs_with_the_call_that_requested_it() -> None:
    """A tool span that starts after the next model call still belongs to its caller."""
    raw = _raw("e" * 32, "2026-09-14T07:00:00Z", "price?", "It is $9.",
               tools=[("search_products", {"query": "vase"}, {"ok": True, "count": 1})])
    gens = [o for o in raw["observations"] if o["type"] == "GENERATION"]
    tool = next(o for o in raw["observations"] if o["type"] == "TOOL")
    tool["startTime"] = gens[1]["startTime"][:-1] + "5Z"  # later than the final model call
    turn = traces.build_turn(raw, None, {})
    assert [[t["name"] for t in s["tools"]] for s in turn["steps"]] == [["search_products"]]
    assert turn["reply_meta"] is not None  # the reply is not repeated as narration


def test_session_map_matches_nearest_stored_message(tmp_path: Path) -> None:
    raws = [_raw("1" * 32, "2026-09-14T07:00:00.200Z", "hello", "hi"),
            _raw("2" * 32, "2026-09-14T07:00:05.100Z", "again", "yes"),
            _raw("3" * 32, "2026-09-14T09:00:00Z", "never stored", "?", scenario="s-2")]
    db = _sessions_db(tmp_path / "s.db", [
        ("old", "hello", "2026-09-13 07:00:00"),  # same text, a day earlier
        ("new", "hello", "2026-09-14 07:00:00"),
        ("new", "again", "2026-09-14 07:00:05"),
    ])
    result = traces.build_session_map(raws, db)
    assert {t: e["session_id"] for t, e in result["traces"].items()} == {"1" * 32: "new", "2" * 32: "new"}
    assert result["unmatched"] == ["3" * 32]
    assert result["scenarios_split_across_sessions"] == []


def test_sessions_group_by_session_id_in_time_order() -> None:
    raws = [_raw("b" * 32, "2026-09-14T07:00:09Z", "second", "2"),
            _raw("a" * 32, "2026-09-14T07:00:01Z", "first", "1"),
            _raw("c" * 32, "2026-09-14T08:00:00Z", "native", "3", scenario="s-9", session="native-sid"),
            _raw("d" * 32, "2026-09-14T08:30:00Z", "orphan", "4", scenario="s-1")]
    mapping = {"a" * 32: "sess-1", "b" * 32: "sess-1"}
    sessions, meta = traces.build_sessions(raws, mapping, {})
    by_id = {s["session_id"]: s for s in sessions}
    assert [t["user"] for t in by_id["sess-1"]["turns"]] == ["first", "second"]
    assert [t["turn"] for t in by_id["sess-1"]["turns"]] == [1, 2]
    assert by_id["native-sid"]["session_source"] == "attribute"
    # Same scenario id, but no session evidence: never merged into sess-1.
    assert by_id["unmatched:" + "d" * 32]["session_source"] == "unmatched"
    assert meta["session_sources"] == {"attribute": 1, "recovered": 1, "unmatched": 1}


def test_restrict_to_export_keeps_only_the_reviewed_run(tmp_path: Path) -> None:
    final = [_raw("a" * 32, "2026-09-14T07:00:00Z", "hi", "yo")]
    export = tmp_path / "support_traces.json"
    export.write_text(json.dumps({"traces": final}))
    live = final + [_raw("p" * 32, "2026-09-12T07:00:00Z", "pilot", "run")]
    kept, excluded = traces.restrict_to_export(live, export)
    assert [r["id"] for r in kept] == ["a" * 32] and excluded == 1
    assert traces.restrict_to_export(live, tmp_path / "missing.json") == (live, 0)


class _FakeScores:
    def __init__(self, store: dict) -> None:
        self.store = store

    def get(self, score_ids: str):
        hit = self.store.get(score_ids)
        return SimpleNamespace(data=[SimpleNamespace(value=hit["value"])] if hit else [])


class _FakeClient:
    def __init__(self) -> None:
        self.scores: dict[str, dict] = {}
        self.api = SimpleNamespace(score_v_2=_FakeScores(self.scores))

    def auth_check(self) -> bool:
        return True

    def create_score(self, *, score_id: str, **kwargs) -> None:
        self.scores[score_id] = kwargs  # Langfuse upserts on score id

    def flush(self) -> None:
        return None


@pytest.fixture
def review_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    server.use_state_dir(tmp_path)
    server._DATA["sessions"] = [{"session_id": "s", "turns": [{"trace_id": "a" * 32}, {"trace_id": "b" * 32}]}]
    server.write_json(tmp_path / "patterns.json", {"modes": [{"name": "unconfirmed_write", "status": "final"}]})
    client = _FakeClient()
    from analysis.helpers import langfuse_io
    monkeypatch.setattr(langfuse_io, "is_configured", lambda: True)
    monkeypatch.setattr(langfuse_io, "_client", lambda: client)
    monkeypatch.setattr(langfuse_io, "ensure_score_config", lambda name, client=None: "cfg-" + name)
    yield tmp_path, client
    server.use_state_dir(traces.STATE_DIR)
    server._DATA["sessions"] = []


def test_label_changes_update_one_langfuse_score(review_state) -> None:
    state, client = review_state
    tid = "a" * 32
    server.append_label({"mode": "unconfirmed_write", "trace_id": tid, "label": 1, "evidence": "queued"})
    assert server.sync_labels()["sent"] == 1
    assert server.current_labels()["unconfirmed_write"][tid]["sync"] == "sent"
    assert server.sync_labels()["verified"] == 1
    assert server.current_labels()["unconfirmed_write"][tid]["sync"] == "verified"

    server.append_label({"mode": "unconfirmed_write", "trace_id": tid, "label": 0})
    assert server.current_labels()["unconfirmed_write"][tid]["sync"] == "pending"
    server.sync_labels()
    assert len(client.scores) == 1  # same score id, updated in place
    (only,) = client.scores.values()
    assert only["value"] == 0 and only["name"] == "unconfirmed_write" and only["trace_id"] == tid
    lines = (state / "labels" / "unconfirmed_write.jsonl").read_text().splitlines()
    assert [json.loads(line)["label"] for line in lines] == [1, 0]


def test_labels_stay_pending_when_langfuse_is_unreachable(review_state, monkeypatch) -> None:
    state, client = review_state
    monkeypatch.setattr(client, "auth_check", lambda: (_ for _ in ()).throw(ConnectionError("refused")))
    server.append_label({"mode": "unconfirmed_write", "trace_id": "b" * 32, "label": 1})
    result = server.sync_labels()
    assert result["sent"] == 0 and "refused" in result["error"]
    assert server.current_labels()["unconfirmed_write"]["b" * 32]["sync"] == "pending"
    assert client.scores == {}


@pytest.mark.parametrize("body", [
    {"mode": "not_in_taxonomy", "trace_id": "a" * 32, "label": 1},
    {"mode": "../escape", "trace_id": "a" * 32, "label": 1},
    {"mode": "unconfirmed_write", "trace_id": "a" * 32, "label": 2},
    {"mode": "unconfirmed_write", "trace_id": "z" * 32, "label": 1},
])
def test_invalid_labels_are_rejected(review_state, body) -> None:
    with pytest.raises(ValueError):
        server.append_label(body)
