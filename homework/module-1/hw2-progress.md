# HW2 progress note (local, not a submission deliverable)

Branch: `homework_2` (created off `main` at 65db317)
Handout: [hw2.md](hw2.md)
Style: interactive tutorial, student drives, one step per go-ahead.

## Current status

Environment synced: `uv sync` reported 140 resolved, 136 audited, nothing to
install. HW1 is complete and merged, so the five support tools and the local
database are in place as the handout requires.

Part A is implemented. Verified with an in-memory OTel exporter: a shopper's
allowed call records user_role, string user_id and `permission_denied=False`;
a merchant's denied call also records integer store_id, `permission_denied=True`
and the reason. Regression check offline: 30 passed, 11 xfailed
(`test_agent_tools`, `test_extra_tools`, `test_auth`, `test_adversarial`).
The remaining xfails are the HW2 holes still to be filled.

**Next:** Part B, `create_session` in `server/app.py`.

## Deliverable checklist

| # | Deliverable | Where | Status |
| --- | --- | --- | --- |
| 0 | Environment synced | — | done |
| 1 | `record_tool_result`, `_set_permission_denied_attributes` | `observability/instrument.py` | **done**, Langfuse check pending in Part E |
| 2 | `create_session` | `server/app.py` | not started |
| 3 | `post_message` in a `cartwheel.session_message` root span | `server/app.py` | not started |
| 4 | Two authentication tests | `tests/test_observability.py` | not started |
| 5 | At least five traced requests, inspected in Langfuse | Part E | not started |
| 6 | Two differing `cartwheel.prompt_version` hashes | Part F | not started |
| 7 | Exactly two trace objects | `hw2-traces.json` | not started |
| 8 | Checks pass (see below) | — | not started |
| 9 | Video, 5 minutes or less | — | **student** |
| 10 | Student assessments | — | **student** |

Files to commit, per the handout: `observability/instrument.py`,
`server/app.py`, `tests/test_observability.py`, `hw2-traces.json`.

## Checks the handout requires

```bash
uv run pytest --runxfail -vv tests/test_hw_holes.py -k "create_session_binds"
uv run pytest --runxfail tests/test_hw_holes.py -k hw2
uv run pytest tests/test_observability.py
uv run pytest
```

## Things to watch

- `test_m2_run_judge_persists_store_predictions_for_prevalence` fails offline in
  this environment with `httpx.ConnectError: Connection refused`. It wants a
  live model and is unrelated to HW2 work. It passes in a clean checkout with
  no `.env`. Do not treat it as an HW2 regression.
- Part E needs `TRACELOOP_TRACE_CONTENT=true` in `.env` before starting the
  server, or message content is omitted from the traces.
- Part F needs the same database state for both runs;
  `uv run python -m seed.generate` resets it.
- Student has not used a terminal HTTP client before, so Part E commands get
  broken down flag by flag.

## Study notes

[homework_2_diagram.md](homework_2_diagram.md) holds the request path diagram,
the span tree with its attribute table, and the session token explanation.
Written alongside the work; not a submission deliverable.
