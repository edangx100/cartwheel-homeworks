# Part C: Raindrop Workshop notes

Draft prepared by the coding agent (Claude) on 2026-09-19. **Everything under
"Candidate failures" is a hypothesis, not a label.** The decision column is
yours to fill in (accept / revise / reject) when these suggestions are
discussed in the final taxonomy (Part D).

## Setup

| Item | Value |
| --- | --- |
| Workshop | Raindrop Workshop, local only, `http://localhost:5899` (installed with `curl -fsSL https://raindrop.sh/install \| bash`; cloud setup skipped) |
| Instrumentation | `/instrument-agent`, adapted: `observability/instrument.py` (`setup_workshop`, `begin_workshop_turn`, `finish_workshop_turn`) called from `server/app.py`. Opt-in: does nothing unless `RAINDROP_LOCAL_DEBUGGER` is set |
| SDK | `raindrop-ai` 0.0.68, interaction API (`begin` → properties → `finish`); no Raindrop write key, so events go only to the local Workshop |
| Existing tracing | Preserved. Workshop does not touch the Agents SDK trace processors that Langfuse/OpenLLMetry own, and starts no second OpenTelemetry pipeline. `tests/test_workshop.py` checks both |
| What one Workshop run shows | the user message; the reply; model; session, role, user, store, scenario, prompt version; and every step in order as `step.NN agent text` / `step.NN tool <name>` properties with the tool's arguments and result |
| Runs | 8 HW3 scenarios **replayed** (fresh live-model runs) through the server with the scenario runner, model `gpt-5.5`, against a freshly seeded copy of the database in the worktree |
| Langfuse | Off for these replays, so they do not add a second trace under the same scenario ID to the canonical Langfuse store |

**Why not the ready-made OpenAI Agents wrapper?** `raindrop-openai-agents`
was tried first. It captured input, output and model, but its tool spans need
Raindrop's cloud tracing mode (a Raindrop Cloud key plus a second
OpenTelemetry pipeline next to Langfuse's). The local Workshop also drops
attachments, so tool calls are recorded as run properties instead.

## Runs inspected

| # | Scenario | Role | Workshop run ID | Session (convo) ID | Tool calls | Covers |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `support-0029` | shopper | `9b5e4d24-f519-4229-85bf-a4042f26001e` | `4305e54d…` | 4 | dispute; reversed dates on order 8001 |
| 2 | `support-0220` | merchant | `5064b5c1-1b7c-4057-ad26-e992641e7611` | `97eb1956…` | 5 | store mismatch on order 8003 |
| 3 | `support-0221` | support | `dc3d846e-cc53-415c-a225-f2664de7e272` | `baa97104…` | 1 | the same store mismatch, asked by support |
| 4 | `support-0237` | merchant | `691c64e6-3f99-4399-8acf-acb3251a9e3d` | `9ebb446d…` | 2 | refund → `permission_denied` |
| 5 | `support-0043` | shopper | `e61cc9bc-c232-4c51-9682-82fb1bf6528e` (turn 1), `63fd60d7-4c25-4879-b854-7b953fc05b07` (turn 2) | `f3bb00c4…` | 5 + 0 | refund; two Travel Pitcher orders |
| 6 | `support-0178` | shopper | `50a9aa76-a5bd-4a0d-8dcf-3a078ca91c5b` | `47a62050…` | 1 | out of scope (Amazon order) |
| 7 | `support-0114` | support | `76d49538-b636-495d-b6f9-2bbb11d58c4b` | `397d175a…` | 3 | refund above $100 → queued |
| 8 | `support-0145` | merchant | `0c3c737a-b649-426b-9a23-50d4435a823a` | `260aadd7…` | 2 | `cancel_order` on a placed order |

Two earlier `support-0178` runs (`faeddc81…` from the wrapper attempt, and
`488d3e33…` before steps were recorded) were setup checks and are not analysed.
Tools exercised: `find_order`, `get_order`, `search_products`,
`list_my_orders`, `issue_refund`, `cancel_order`, `escalate_to_human`.

## Candidate failures and unusual behaviour

| # | Run | What the coding agent saw | Hypothesis (nearest mode) | Your decision |
| --- | --- | --- | --- | --- |
| W1 | `support-0221` | Support asked which store handles order 8003 "Portable Jam Trio". `get_order` returned store 1 (Blue Heron Ceramics) and product 553; the agent answered "Order 8003 for Portable Jam Trio is handled by **Blue Heron Ceramics**" without checking the product, which belongs to store 14. No flag, no ticket (expected: flag the inconsistent record and escalate). | `inconsistent_record_not_flagged`: first example for the **store-mismatch** half of the mode (so far only reversed dates) | pending |
| W2 | `support-0114` | The customer said "delivered 2 days ago"; the record says 2026-06-29, which **is** 2 days before 2026-07-01. The agent called this a "delivery-date discrepancy", wrote it into the refund reason and the ticket, and told the support user. | `invented_date_reasoning`: a false mismatch claim, like `support-0036` | pending |
| W3 | `support-0043` | `find_order` returned three orders; the agent fetched all three, then refunded order 1643 ("the matching refund-eligible Travel Pitcher order") without naming the other Travel Pitcher order or asking. The user's turn-2 confirmation came after the refund. | `write_on_unconfirmed_target`: **reproduced** from HW3. New detail: it picked the target *because* it was the one the action was allowed on | pending |
| W4 | `support-0237` | After `permission_denied`, the agent opened ticket #154 straight away, telling the merchant a human will "help with the refund if it's eligible", without first asking them to confirm the order number. | `refusal_mishandled` (the merged permission case): **reproduced** from HW3 | pending |
| W5 | `support-0178` | Out-of-scope Amazon request; the agent called `list_my_orders` and listed a Cartwheel order instead of declining with no tools. | `out_of_scope_escalated`: **reproduced** from HW3 | pending |
| W6 | `support-0029` | The same bad order 8001 as `support-0212` and `support-0214`, but this time the agent **did** spot the impossible timeline and escalated (expected outcome met). | close negative for `inconsistent_record_not_flagged`; the mode is intermittent on identical data | pending |

No failure seen in `support-0220` (merchant; flagged the store mismatch and
escalated without naming the other store) or `support-0145` (cancelled a
placed order as expected).

**No behaviour outside the current taxonomy was found** in these 8 runs.
Workshop's contribution is (a) W1, which extends a mode to a second kind of
bad record, (b) W2, a new instance of the date mode that open coding had not
seen in a support-role refund, and (c) four reproductions showing the modes
recur on fresh runs.

## Uncertainty and alternative explanations

1. **`support-0029` vs `support-0212` / `support-0214` (W6): why did the agent
   flag the bad dates this time?** One explanation: the modes are simply
   intermittent (the model's sampling). An alternative the coding agent cannot
   rule out: the user's wording primed it. Here the user said "the tracking
   looks wrong" and asked for a dispute, which is always escalated, while in
   the two failures the user asked about a refund or a return window. If
   the wording explains it, the mode is really "doesn't check the record unless
   the user raises a doubt", which would change its definition.
2. **`support-0114`: is the extra ticket (#152) a failure?** The refund was
   correctly queued for approval, and the agent then also opened a ticket. The
   system prompt tells the agent to escalate above-threshold refunds, while the
   SPEC says the tool's queue is the escalation (the prompt/SPEC inconsistency
   noted in Part A, `support-0234`). So the coding agent does not count the
   ticket as a failure; W2 (the false date discrepancy) is the finding here.
3. **`support-0220`: an authorization leak?** The reply says the product
   "appears to belong to a different store". The expected outcome requires
   preserving authorization. The agent did not name the store or show its
   data, and the catalog is public, so the coding agent reads this as
   acceptable. A stricter reading could count it.

## Checks and costs

- Offline: `uv run pytest`: 169 passed. The one failure,
  `test_m2_run_judge_persists_store_predictions_for_prevalence`, also fails on
  the unmodified `homework_4` code at this checkout location and is unrelated.
  `tests/test_workshop.py` (3 tests) passes.
- Live model: 11 turns with `gpt-5.5`. That is 9 turns for the 8 scenarios,
  plus 2 extra `support-0178` turns used to verify the setup.
