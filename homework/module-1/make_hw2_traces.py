"""Build hw2-traces.json from Langfuse.

The handout expects these seven fields to be copied from the Langfuse UI by
hand. This reads the same values through the Langfuse API instead, so a
32-character trace id cannot be mistyped. It is not required by the
assignment.

Usage, from the repository root:

    uv run python homework/module-1/make_hw2_traces.py TRACE_ID TRACE_ID

Reads the LANGFUSE_* keys from .env and never prints them.
"""
import base64, json, os, sys, urllib.request
from pathlib import Path

# Run from a subfolder, so put the repository root on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from observability.instrument import load_env  # noqa: E402

load_env()
host = os.environ["LANGFUSE_HOST"].rstrip("/")
auth = base64.b64encode(
    f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
).decode()

def api(path):
    req = urllib.request.Request(host + path, headers={"Authorization": f"Basic {auth}"})
    return json.load(urllib.request.urlopen(req, timeout=30))

trace_ids = sys.argv[1:]
if len(trace_ids) != 2:
    sys.exit("give exactly two trace ids")

project_id = api("/api/public/projects")["data"][0]["id"]
records = []
for tid in trace_ids:
    obs = api(f"/api/public/traces/{tid}")["observations"]
    root = next(o for o in obs if o["name"] == "cartwheel.session_message")
    attrs = (root.get("metadata") or {}).get("attributes") or {}
    tools = sorted((o for o in obs if o["type"] == "TOOL"), key=lambda o: o["startTime"])
    records.append({
        "trace_id": tid,
        "permalink": f"{host}/project/{project_id}/traces/{tid}",
        "prompt_version": attrs["cartwheel.prompt_version"],
        "user_role": attrs["cartwheel.user_role"],
        "user_id": attrs["cartwheel.user_id"],
        "tool_order": [o["name"] for o in tools],
        "final_status": "error" if any(o.get("level") == "ERROR" for o in obs) else "completed",
    })

with open("hw2-traces.json", "w") as f:
    json.dump(records, f, indent=2)
    f.write("\n")
print(f"wrote hw2-traces.json ({len(records)} traces, project {project_id})")
