# HW1 progress note (local, not part of the submission)

Branch: `homework_1` (created off `main`)
Style: instructor tutorial (`hw1-tutorial.md`)

## Current status
Part A five required tools implemented in `agent/tools.py` and passing. Next:
Part B conversations. The additional tool is still outstanding.

Observations parked for later:
- `get_order` returns `product_id` only, no product title, so the agent cannot
  name what was ordered. Candidate gap for the Part A additional tool.
- Reply asserted "Refund eligible: Yes" with no policy identifier and no return
  window. Candidate Part C requirement to examine (RESP-1).

## Demo order facts (seed, unchanged)
- 4127: Heavy-Duty Vase, $84.00, delivered, refund_eligible=True (store 1)
- 3980: Heavy-Duty Vase, $52.00, delivered, refund_eligible=False (outside window)
- 4455: Heavy-Duty Vase, $240.00, delivered, refund_eligible=True (over $100 threshold)

## Environment observed (2026-09-08)
- `data/cartwheel.db` and `data/policies/` already generated.
- `.env`: `OPENAI_API_KEY` + `CARTWHEEL_MODEL=gpt-5.5`, verified working with a live call.
- All five HW1 tools in `agent/tools.py` still raise `NotImplementedError`.
- `hw1-session.jsonl` does not exist yet.
- `uv sync` clean (136 packages audited).
- Baseline `uv run pytest`: 109 passed, 12 skipped, 27 xfailed (offline, no model).
- `pytest --runxfail tests/test_hw_holes.py -k hw1`: 5 failed with NotImplementedError, as expected.
- CLI reads stdin, so one piped invocation = one fresh session (good for Part B isolation).

## Deliverable checklist
- [x] Part A: `get_policy`
- [x] Part A: `search_products`
- [x] Part A: `list_my_orders`
- [x] Part A: `cancel_order`
- [x] Part A: `find_order`
- [x] Part A: `list_orders_by_status`, registered for shopper and merchant, 8 tests
- [x] Part A: `uv run pytest --runxfail tests/test_hw_holes.py -k hw1` -> 5 passed
- [x] Part A: regression `tests/test_agent_tools.py tests/test_auth.py tests/test_eligibility.py` -> 24 passed
- [x] Part B: 12 conversations in `hw1-session.jsonl`, all three roles, all six required cases
- [x] Part C: ESC-2 omission found, tested, revised; before/after in `hw1-part-c.md`
- [ ] Commits: `agent/tools.py`, `agent/agent.py` (if revised), `hw1-session.jsonl`
- [ ] Video, <= 5 minutes, recorded by the student (PENDING)

## Study notes
`explain_code/` holds plain-language walkthroughs written alongside the work
(index + the `find_order` matching deep dive). Not a submission deliverable.

## Upstream contract change (2026-09-10)
Merging `origin/main` brought `d5aada8`, which rewrote the `find_order` contract
after this work was recorded: search the complete authorised scope through
`db.list_order_search_candidates`, keep the helper's newest-first order, return
`to_public_dict()` unchanged (so no `product_title`), and reject an unsupported
role instead of falling back to all orders. `find_order` was rewritten to match
and `tests/test_hw_holes.py -k hw1` passes, 8 tests. Fixing it also exposed a
real bug in `_match_score`: containment against a one- or two-letter title token
("the c in USB-C") scored 0.95 against any query containing that letter. The old
20-order cap hid it; support's full-table scope did not.

Part B transcripts were NOT re-run. See the C10 note in `hw1-part-b-plan.md`.

## Next step
The video. Everything else is done: Part A (five tools plus
`list_orders_by_status`), Part B (`hw1-session.jsonl`, written up in
`hw1-part-b-plan.md`), Part C (`hw1-part-c.md`).
