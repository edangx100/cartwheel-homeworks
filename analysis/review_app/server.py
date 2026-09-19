"""Homework 4 review server: session-grouped traces, notes, taxonomy, labels.

A standard-library HTTP server for ``ui/index.html``. It keeps the reference
interface's file-backed JSON API (``analysis/server.py``) and adds what the
Cartwheel traces need: session-grouped conversations, per-trace binary labels,
a sample manifest, and a Langfuse score sync that reports pending writes.

    GET  /                      the review app
    GET  /api/meta              trace source, counts, shared prompt and schemas
    GET  /api/sessions          conversations grouped by cartwheel.session_id
    POST /api/reload            reload traces from the configured source
    GET  /api/manifest          analysis/state/sample_manifest.json
    POST /api/manifest
    GET  /api/annotations       analysis/state/annotations.json
    POST /api/annotations
    GET  /api/patterns          analysis/state/patterns.json
    POST /api/patterns
    GET  /api/suggestions       analysis/state/suggestions.json
    POST /api/suggestions
    GET  /api/labels            current label per mode and trace, with sync state
    POST /api/labels            record one accepted judgment and sync it
    POST /api/sync              retry pending Langfuse writes and verify sent ones

Labels. A judgment is 1 when the failure is present and 0 when it is absent.
Each accepted judgment is appended to ``analysis/state/labels/<mode>.jsonl``
(latest line per trace wins) and written to Langfuse as a numeric score named
after the mode. The score id is derived from the trace and mode, so changing a
judgment updates the same score instead of adding a duplicate.
``analysis/state/label_sync.json`` records which label each score carries.

Run from the repository root:

    uv run python -m analysis.review_app.server              # Langfuse, else export
    uv run python -m analysis.review_app.server --source export
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from analysis.review_app import traces as trace_store

HERE = Path(__file__).resolve().parent
UI_FILE = HERE / "ui" / "index.html"
STATE_DIR = trace_store.STATE_DIR
LABEL_DIR = STATE_DIR / "labels"
SYNC_LEDGER = STATE_DIR / "label_sync.json"
MODE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SCORE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "cartwheel/hw4/labels")

STATE_FILES: dict[str, tuple[Path, Any]] = {}


def use_state_dir(state_dir: Path) -> None:
    """Point every state file at ``state_dir`` (tests use a temporary copy)."""
    global STATE_DIR, LABEL_DIR, SYNC_LEDGER
    STATE_DIR = Path(state_dir)
    LABEL_DIR = STATE_DIR / "labels"
    SYNC_LEDGER = STATE_DIR / "label_sync.json"
    STATE_FILES.update(
        {
            "/api/manifest": (STATE_DIR / "sample_manifest.json", {"batches": {}, "items": []}),
            "/api/annotations": (STATE_DIR / "annotations.json", {"annotations": []}),
            "/api/patterns": (STATE_DIR / "patterns.json", {"modes": []}),
            "/api/suggestions": (STATE_DIR / "suggestions.json", []),
        }
    )


use_state_dir(STATE_DIR)

_LOCK = threading.Lock()
_DATA: dict[str, Any] = {"sessions": [], "meta": {}}
_CONFIG: dict[str, Any] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data: Any) -> None:
    """Write atomically so a crash never leaves half a state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# traces
# ---------------------------------------------------------------------------

def load_data() -> None:
    raws, source = trace_store.load_traces(_CONFIG["source"], _CONFIG["export"])
    sessions, meta = trace_store.build_sessions(
        raws,
        trace_store.load_session_map(),
        trace_store.load_scenarios(_CONFIG["scenarios"]),
        trace_store.langfuse_host(),
    )
    meta["source"] = source
    meta["loaded_at"] = _now()
    with _LOCK:
        _DATA["sessions"], _DATA["meta"] = sessions, meta


# ---------------------------------------------------------------------------
# labels and Langfuse scores
# ---------------------------------------------------------------------------

def score_id(trace_id: str, mode: str) -> str:
    return str(uuid.uuid5(SCORE_NAMESPACE, f"{trace_id}/{mode}"))


def taxonomy_modes() -> list[str]:
    patterns = read_json(*STATE_FILES["/api/patterns"])
    return [m["name"] for m in patterns.get("modes", []) if MODE_NAME.match(m.get("name", ""))]


def read_label_log(mode: str) -> list[dict[str, Any]]:
    path = LABEL_DIR / f"{mode}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def current_labels() -> dict[str, Any]:
    """Latest judgment per mode and trace, annotated with its sync state."""
    ledger = read_json(SYNC_LEDGER, {})
    out: dict[str, dict[str, Any]] = {}
    for mode in taxonomy_modes():
        latest: dict[str, Any] = {}
        for record in read_label_log(mode):
            latest[record["trace_id"]] = record
        for trace_id, record in latest.items():
            entry = ledger.get(score_id(trace_id, mode), {})
            if entry.get("label_id") != record["label_id"]:
                record["sync"] = "pending"
            else:
                record["sync"] = entry.get("state", "pending")
        out[mode] = latest
    return out


def append_label(body: dict[str, Any]) -> dict[str, Any]:
    mode = str(body.get("mode", ""))
    trace_id = str(body.get("trace_id", ""))
    if not MODE_NAME.match(mode) or mode not in taxonomy_modes():
        raise ValueError(f"unknown failure mode: {mode!r}")
    if body.get("label") not in (0, 1):
        raise ValueError("label must be 0 (absent) or 1 (present)")
    if not any(t["trace_id"] == trace_id for s in _DATA["sessions"] for t in s["turns"]):
        raise ValueError(f"unknown trace: {trace_id!r}")
    history = [r for r in read_label_log(mode) if r["trace_id"] == trace_id]
    record = {
        "trace_id": trace_id,
        "label": int(body["label"]),
        "source": body.get("source") or "human",
        "ts": _now(),
        "label_id": f"{trace_id}#{len(history)}",
    }
    for key in ("evidence", "suggestion_id", "session_id"):
        if body.get(key):
            record[key] = body[key]
    path = LABEL_DIR / f"{mode}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def sync_labels() -> dict[str, Any]:
    """Send pending judgments to Langfuse, then verify previously sent ones.

    Langfuse ingestion is asynchronous, so a write is ``sent`` after the
    client flushes and ``verified`` only after the score is read back with
    the same value. Nothing is marked synced while Langfuse is unreachable.
    """
    from analysis.helpers import langfuse_io

    labels = current_labels()
    todo = [(m, r) for m, recs in labels.items() for r in recs.values() if r["sync"] != "verified"]
    result = {"sent": 0, "verified": 0, "pending": len(todo), "error": None}
    if not todo:
        return result
    try:
        if not langfuse_io.is_configured():
            raise RuntimeError("LANGFUSE_* variables are not set")
        client = langfuse_io._client()
        if not client.auth_check():
            raise RuntimeError("Langfuse auth check failed")
    except Exception as exc:  # noqa: BLE001 - surfaced in the progress view
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return result

    ledger = read_json(SYNC_LEDGER, {})
    configs: dict[str, str] = {}
    for mode, record in todo:
        sid = score_id(record["trace_id"], mode)
        entry = ledger.get(sid, {})
        try:
            if entry.get("label_id") == record["label_id"] and entry.get("state") == "sent":
                found = client.api.score_v_2.get(score_ids=sid).data or []
                if any(float(getattr(s, "value", -1)) == record["label"] for s in found):
                    entry["state"], entry["verified_at"] = "verified", _now()
                    result["verified"] += 1
                continue
            if mode not in configs:
                configs[mode] = langfuse_io.ensure_score_config(mode, client=client)
            client.create_score(
                score_id=sid,
                name=mode,
                value=record["label"],
                trace_id=record["trace_id"],
                data_type="NUMERIC",
                config_id=configs[mode],
                comment=record.get("evidence"),
                metadata={"label_id": record["label_id"], "source": record["source"]},
            )
            ledger[sid] = {
                "trace_id": record["trace_id"],
                "mode": mode,
                "label_id": record["label_id"],
                "value": record["label"],
                "state": "sent",
                "sent_at": _now(),
            }
            result["sent"] += 1
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"[:300]
            break
    client.flush()
    write_json(SYNC_LEDGER, ledger)
    result["pending"] = sum(
        1 for recs in current_labels().values() for r in recs.values() if r["sync"] != "verified"
    )
    return result


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"null")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html"}:
            self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/meta":
            self._json(_DATA["meta"])
        elif path == "/api/sessions":
            self._json(_DATA["sessions"])
        elif path == "/api/labels":
            self._json(current_labels())
        elif path in STATE_FILES:
            self._json(read_json(*STATE_FILES[path]))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            if path in STATE_FILES:
                body = self._body()
                expected = type(STATE_FILES[path][1])
                if not isinstance(body, expected):
                    raise ValueError(f"{path} expects a JSON {expected.__name__}")
                with _LOCK:
                    write_json(STATE_FILES[path][0], body)
                self._json({"ok": True})
            elif path == "/api/labels":
                with _LOCK:
                    record = append_label(self._body())
                    sync = sync_labels() if _CONFIG["auto_sync"] else None
                self._json({"ok": True, "record": record, "sync": sync})
            elif path == "/api/sync":
                with _LOCK:
                    self._json({"ok": True, "sync": sync_labels()})
            elif path == "/api/reload":
                load_data()
                self._json({"ok": True, "meta": {k: v for k, v in _DATA["meta"].items() if k != "registry"}})
            else:
                self._json({"error": "not found"}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"ok": False, "error": str(exc)}, 400)


def main() -> None:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description="Homework 4 review interface")
    parser.add_argument("--port", type=int, default=8030)
    parser.add_argument("--source", choices=["auto", "langfuse", "export"], default="auto")
    parser.add_argument("--export", type=Path, default=trace_store.DEFAULT_EXPORT)
    parser.add_argument("--scenarios", type=Path, default=trace_store.DEFAULT_SCENARIOS)
    parser.add_argument(
        "--no-auto-sync", dest="auto_sync", action="store_false",
        help="record labels locally and sync only when Sync is pressed",
    )
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    args = parser.parse_args()
    load_dotenv(trace_store.REPO / ".env")
    use_state_dir(args.state_dir)
    _CONFIG.update(vars(args))
    load_data()
    meta = _DATA["meta"]
    print(
        f"{meta['session_count']} sessions / {meta['trace_count']} traces from {meta['source']}; "
        f"session ids {meta['session_sources']}"
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"review app on http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
