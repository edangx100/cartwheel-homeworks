# Part A: review in the standard Langfuse view

Five traces reviewed in the standard Langfuse trace view on 2026-09-18, before the review interface existed. This file restores the record from that Claude Code session (`57cc8575`), where it was kept in chat only. Friction notes quote the reviewer's own words. Open codes are the wording adopted in that chat.

These five are **pre-batch observations**. They don't count toward the 100 reviewed traces. The open codes are imported into `analysis/state/annotations.json` with `batch: "part_a"`, and the sampler never redraws these traces.

## Traces reviewed

| # | Scenario | Trace reviewed | Role | Turns | First failure | Requirement |
|---|---|---|---|---|---|---|
| 1 | `support-0248` | `afe1280ca04d0fb875e9cb74595822dd` (turn 1) | shopper | 2 | none observed | — |
| 2 | `support-0246` | `3503abdfad27bcefc55672c68d0fb695` | support | 1 | reply shows an unverified product name as order data | pending revision #2 |
| 3 | `support-0242` | `cc93a580370b4336aacd5b81607aaa3b` (turn 1) | merchant | 2 | refund on an inferred order and amount without asking | pending revision #3 |
| 4 | `support-0234` | `5a1588a63cdc06f155132ff36409c889` | shopper | 1 | delivery-date mismatch ignored before a $161 refund | RESP-3 |
| 5 | `support-0249` | `065b25b9a3789d83ff7da86558aa2c55` (turn 1) | merchant | 2 | permission-denied cancel escalated instead of asking; ticket left open | pending revision #4 |

## Friction in the standard Langfuse view (reviewer's words)

| # | Scenario | Friction |
|---|---|---|
| 1 | `support-0248` | "can't tell what turn within N turns a trace is in Langfuse, need to do so manually which is error prone". "i could not have judge turn 2 without looking at turn 1." "tool result easy to line up with the reply." "I cannot see which policy the reply cited" (because no retrieval tool was called; the reply made no policy claim). |
| 2 | `support-0246` | "need to read text within nested JSON to read about intermediate reasoning and tool call results. Not humanly easy to read" |
| 3 | `support-0242` | "Can't tell turn order, and finding it by hand is error prone" |
| 4 | `support-0234` | "Friction was the same as #2 - Nested JSON hard to read text within" |
| 5 | `support-0249` | "Can't tell turn order. Turn 2 can't be judged without turn 1." |

**Patterns:**
- Turn order was a problem in 3 of 3 multi-turn traces (#1, #3, #5).
- Nested JSON was a problem in 2 of 2 single-turn traces (#2, #4).
- The system prompt and tool schemas repeat on every model call (noticed in #2 and visible in all five).

## Open codes

1. **`support-0248`:** no failure observed.
2. **`support-0246`** (the reply): "Reply lists 'Item: Classic Scarf' alongside the verified order fields, but get_order returned only product_id: 591; the product name came from the user's message and was never checked against the order."
3. **`support-0242`** (turn 1, the `issue_refund` call): "Merchant asked to refund 'a customer's Compact Trowel Set order' with no order number or amount; agent picked order 753 from a 5-result fuzzy search and issued a full $57 refund (reason text says 'Merchant requested full refund') without asking which order or how much."
   - *Close negative for #2:* "Compact Trowel Set" here **is** tool-verified (`search_products` → product 106).
4. **`support-0234`** (the `issue_refund` call): "User said the Classic Tea Sampler was 'delivered today', but find_order/get_order show order 7249 delivered 2026-07-01; agent never mentioned the mismatch and issued a $161 refund on that order anyway."
   - *Close negative for the handout's `unconfirmed_write` example:* the reply says the refund was requested and needs human approval, which matches the tool's queued status.
5. **`support-0249`** (turn 1, the `escalate_to_human` call): "Merchant (store 16) asked to cancel order 1468; get_order returned permission_denied, and instead of asking the merchant to confirm the number, the agent opened ticket 238 asking a human to 'assist with cancellation if appropriate' on another store's order. In turn 2 the merchant corrected it to 3416 (a typo), but ticket 238 was never mentioned or withdrawn."
   - **Please confirm the wording.** The chat took "go" as adopting this draft.

## Pending SPEC revisions (not yet written to `SPEC.md`)

| # | Draft requirement | Motivated by | Relation |
|---|---|---|---|
| 1 | When a dispute appears to be outside the `cw-disputes` window, the agent states that it is likely ineligible, cites the policy, and still escalates for a final human decision. | `support-0246` | Clarifies ESC-3 |
| 2 | Do not present user-supplied details as verified order data; label them as reported by the user or verify them with a tool. | `support-0246` | Clarifies RESP-3 (invented values) to cover unverified user claims |
| 3 | Before a write action (refund, cancel), if the user did not specify the target order or the amount, and the lookups do not identify exactly one candidate, ask the user rather than choosing. | `support-0242` | Clarifies RESP-3 for write actions |
| 4 | When a tool returns `permission_denied` for an order the user named, tell the user the order can't be accessed and ask them to confirm the order number. Do not open a ticket requesting action on an order outside the caller's scope unless the user confirms the number and the request still needs a human. | `support-0249` | Clarifies ESC-3 and AUTH-1 |

## Risk notes (not failures in these traces)

- **`support-0246`:** the date used for the 60-day dispute check has no source in the prompt or tool results. The conclusion was correct.
- **`support-0242`:** after the refund, `get_order` still returns `refund_eligible: true` on an order whose status is `refunded`. An agent that checks only `refund_eligible` could issue a duplicate refund.
- **`support-0246`:** the reply implies the dispute is ineligible but never says so. Under revision #1 this is a borderline pass.

## Tool and specification notes

- **Tool contract (`support-0242`):** TOOL-3's `store` parameter for `search_products` doesn't say whether it takes an ID or a name. The agent passed `"3"` and got `not_found`, then recovered. The reviewer judged this a tool-contract ambiguity, not an agent failure.
- **Prompt vs SPEC (`support-0234`):** the system prompt says to escalate above-threshold refunds, while ESC-1 says the tool queues them and the agent explains. The agent did both, opening ticket 227 on top of queued refund 608. This is recorded as an inconsistency, not a failure.
- **`support-0249`, other observations:** the turn 2 fallout (ticket 238 left open) was judged part of the same failure. A third observation was judged too subtle to count.

## Trace-structure notes for the interface

- There's no `cartwheel.session_id` on any trace, so each turn appears as an unrelated trace in Langfuse.
- Tool-call IDs differ between a generation's output (`call_…`) and the next input (`fc_…`), so calls must be paired with results by span order.
- `cartwheel.permission_denied` appears only in tool-span metadata.
