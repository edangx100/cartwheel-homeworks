"""HW4 Part C: the opt-in Raindrop Workshop mirror must not disturb Langfuse.

Workshop records one Raindrop interaction per turn and must leave the Agents
SDK's process-wide trace processors (which Langfuse owns) untouched. It does
nothing unless RAINDROP_LOCAL_DEBUGGER is set. No model, Langfuse, or running
Workshop is needed: no interaction is started here.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from agents.tracing import get_trace_provider

from agent.auth import AuthContext
from observability import instrument


def _processors() -> list[Any]:
    return list(get_trace_provider()._multi_processor._processors)


@pytest.fixture
def no_workshop(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(instrument, "_workshop", None)
    yield
    instrument.shutdown_workshop()


def test_workshop_is_off_without_the_env_var(no_workshop: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAINDROP_LOCAL_DEBUGGER", raising=False)
    assert instrument.setup_workshop() is False
    turn = instrument.begin_workshop_turn(
        AuthContext(user_id=1, role="shopper"), session_id="s", message="hi",
        scenario_id=None, prompt_version="v", model=None,
    )
    assert turn is None
    instrument.finish_workshop_turn(turn, result=None)  # a no-op, not an error


def test_workshop_leaves_the_sdk_trace_processors_alone(
    no_workshop: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAINDROP_LOCAL_DEBUGGER", "http://localhost:5899/v1/")
    monkeypatch.delenv("RAINDROP_WRITE_KEY", raising=False)
    before = _processors()
    assert instrument.setup_workshop() is True
    assert _processors() == before


def _item(type_: str, **fields: Any) -> SimpleNamespace:
    return SimpleNamespace(type=type_, **fields)


def test_workshop_steps_pair_each_tool_call_with_its_result() -> None:
    items = [
        _item("tool_call_item", call_id="c1",
              raw_item={"name": "get_order", "arguments": json.dumps({"order_id": 7})}),
        _item("tool_call_output_item", call_id="c1", output=json.dumps({"ok": True, "order": {"order_id": 7}})),
        _item("tool_call_item", call_id="c2", raw_item=SimpleNamespace(name="escalate_to_human", arguments="{}")),
        _item("tool_call_output_item", call_id="c2", output="not json"),
    ]
    steps = instrument.workshop_steps(items)
    assert [s["name"] for s in steps] == ["step.01 tool get_order", "step.02 tool escalate_to_human"]
    first = json.loads(steps[0]["value"])
    assert first == {"arguments": {"order_id": 7}, "result": {"ok": True, "order": {"order_id": 7}}}
    assert json.loads(steps[1]["value"])["result"] == "not json"
