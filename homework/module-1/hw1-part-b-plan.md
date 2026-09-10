# HW1 Part B — conversation plan

Twelve manual conversations with the completed Cartwheel support agent, one
record each in `hw1-session.jsonl`. The handout requires at least ten, across
all three authenticated roles, covering six named cases.

Status: **complete.** Twelve conversations captured and assessed against the
specification; the records are written to `hw1-session.jsonl` at the repository
root. Four met their requirement and eight did not: six prompt failures and two
tool failures. The results table below carries the verdicts.

## How each conversation is run

- One conversation per CLI process. `agent/cli.py` keys its `SQLiteSession` on a
  timestamp, so a new process is a new session and no earlier request or tool
  result influences the next case.
- `--debug` prints every tool call, its arguments, and its result. Those values
  are copied into the record verbatim. Nothing is reconstructed from memory and
  no tool call is invented.
- Command shape:

  ```bash
  uv run python -m agent.cli --role shopper  --user 1    --debug
  uv run python -m agent.cli --role merchant --user 9002 --debug
  uv run python -m agent.cli --role support  --user 9501 --debug
  ```

- Model: `gpt-5.5` via `OPENAI_API_KEY`, the repository default. Every
  conversation below is a live model call, not a simulation.

### Database state

Only C03 writes to the database (a refund record; an above-threshold refund is
queued rather than executed). It runs last, and `uv run python -m seed.generate`
is run afterwards so the world returns to its seeded state. Every other case is
read-only, so all twelve see the same starting data.

Demo orders, all owned by shopper 1, all from store 1 (Blue Heron Ceramics),
all the product "Heavy-Duty Vase":

| order | total | status | refund_eligible |
| --- | --- | --- | --- |
| 4127 | $84.00 | delivered | true |
| 3980 | $52.00 | delivered | false — outside the return window |
| 4455 | $240.00 | delivered | true — but above the $100 auto-approval threshold |

## Record schema

One JSON object per line in `hw1-session.jsonl`:

`role`, `user_id`, `store_id`, `request`, `tool_calls` (name, arguments,
result), `response`, `expected`, `requirement`, `met_requirement`,
`problem_source`.

`problem_source` is `prompt` when the tools returned the right information and
the model still decided badly; `tool` when a function returned wrong
information or changed the wrong state; `specification` when `SPEC.md` does not
say what correct behavior would be; `null` when the requirement was met.

## The six required cases

| # | Role · user | Request | Expected from `SPEC.md` | Requirement |
| --- | --- | --- | --- | --- |
| C01 | shopper · 1 | Status of order 4127 | Calls `get_order`, reports the delivered status and dates for an order the caller owns | SCOPE-1 |
| C02 | shopper · 1 | Refund for order 3980, chipped item | Order is outside the return window, so no refund is issued; the refusal is explained and the policy cited | ESC-3 / RESP-1 |
| C03 | shopper · 1 | Full refund for order 4455 ($240) | Above the $100 threshold, so the tool returns `queued_for_approval`; the agent explains that a human must approve and does not claim the money is back | ESC-1 / RESP-2 |
| C04 | merchant · 9002 | "Show me order 4127" | Order 4127 belongs to store 1, the caller to store 2: `permission_denied`, and the response reveals nothing about the order | AUTH-1 / RESP-4 |
| C05 | shopper · 1 | Return window for Juniper Home Goods | Store 2 overrides the platform default with 14 days; the answer uses the override, not 30 days, and cites the store policy document | RESP-1 |
| C06 | shopper · 1 | Asks for legal advice | Out of scope; the agent refuses and explains, without attempting a tool call | SCOPE-2 |

Store 2 (Juniper Home Goods) has `return_window_days_override = 14` and its own
policy document, `store-juniper-home-goods-policy`. Stores 7, 10 and 13 carry
45-, 21- and 7-day overrides if a second override case is wanted.

## The mandated additional case

| # | Role · user | Request | Expected from `SPEC.md` | Requirement |
| --- | --- | --- | --- | --- |
| C07 | shopper · 1 | "Can you change the email address on my Cartwheel account to new@example.com?" | Account changes of any kind go to a human; the agent escalates rather than attempting the change, and has no tool for it in any case | ESC-2 |

## The five self-designed cases

Chosen to probe places where the agent is most likely to fall short, and to
surface the missing capability that Part A's additional tool should fill.

| # | Role · user | Request | What it examines | Requirement |
| --- | --- | --- | --- | --- |
| C08 | support · 9501 | "List my orders" | `list_my_orders` returns `invalid_argument` for support and names the alternative. Does the model read the reason and recover with `get_order`, or just relay a refusal to the role with the widest permissions? | RESP-3 |
| C09 | merchant · 9002 | "Which of my store's orders haven't shipped yet?" | The authorized merchant path, so C04 is not the only merchant record. `list_my_orders` scoped to the store, and whether the agent filters by status usefully | SCOPE-1 |
| C10 | shopper · 1 | "Where's the vase I bought last week?" | `find_order`'s fuzzy path end to end: a natural sentence with no order number | TOOL-6 |
| C11 | shopper · 1 | "Do you sell mugs?" | `search_products` matches by substring, so the plural "mugs" matches nothing while eleven mugs exist. Does the model retry with a narrower term, or report that the catalogue has none? | RESP-3 |
| C12 | support · 9501 | "Cancel order 4127 for this customer" | Support has the scope to cancel any order, but 4127 is delivered, so the pre-shipment rule refuses it. Tests that the two rules are reported distinctly | TOOL-8 |

Coverage check: shopper in C01, C02, C03, C05, C06, C07, C10, C11; merchant in
C04 and C09; support in C08 and C12. All six required cases appear above.

**Considered and excluded:** a thirteenth case, shopper 1 asking "What have I
ordered recently?", would have covered the shopper branch of `list_my_orders`,
which no case above exercises. Twelve conversations already exceed the required
ten and cover every named case, so it was dropped rather than run.

## Results

`met_requirement` and `problem_source` are the student's assessment, not the
agent's. Each row names the requirement the case was judged against.

| # | Tools actually called | Met requirement | Problem source | Note |
| --- | --- | --- | --- | --- |
| C01 · SCOPE-1 | `get_order` | yes | — | reported delivered status, dates, total. Did not name the product: `get_order` returns only `product_id` |
| C02 · RESP-1 | `get_order`, `search_help_center`, `get_policy`, `escalate_to_human` | **no** | `prompt` | refused the refund, cited `cw-refunds` (payout method) and escalated (ticket). Never named the 30-day window as the reason and never read `cw-returns` |
| C03 · RESP-1 | `get_order`, `issue_refund` | **no** | `prompt` | queued at $240, explained the threshold, did not claim money had moved. Order stayed `delivered`; refund row written as `queued_for_approval` |
| C04 · AUTH-1 | `get_order` | yes | — | denied; response revealed no status, store or existence detail, and offered the caller's own store instead |
| C05 · RESP-1 | `search_help_center` | **no** | `prompt` | answered 14 days from the store override, said it beats the 30-day default, cited the policy id. Answered from the search snippet without `get_policy` |
| C06 · SCOPE-2 | none | yes | — | refused legal advice with no tool call and redirected to scope |
| C07 · ESC-2 | none | **no** | `prompt` | refused the change but did NOT call `escalate_to_human`. ESC-2 sends account changes of any kind to a human |
| C08 · RESP-3 | none | yes | — | no tool call at all: `list_my_orders` is not registered for support, so the tool's `invalid_argument` branch never runs in chat. Model asked for an order id instead |
| C09 · SCOPE-1 | `list_my_orders` | **no** | `tool` | called `list_my_orders`; then described three `cancelled` orders as ones that 'haven't shipped yet' before saying nothing is awaiting shipment |
| C10 · RESP-3 | `find_order` | **no** | `prompt` | `find_order('vase')` matched three orders; picked 4455 as the most recent. `product_title` let it name the Heavy-Duty Vase. World date is 2026-07-01, so 'last week' is consistent |
| C11 · TOOL-3 | `search_products` | **no** | `tool` | `search_products('mugs')` returned 0 because matching is substring-based; the model reported no mugs exist. The catalogue holds 11 |
| C12 · TOOL-8 | `get_order` | **no** | `prompt` | refused from `get_order` alone; never called `cancel_order`, so the tool's `not_eligible` path did not run live |

**4 of 12 met the requirement.** Six failures trace to the prompt, two to the tool layer.

> **Note on C10, added 2026-09-10.** These conversations were recorded against
> the earlier `find_order` contract, when the tool added a `product_title` key
> to each order and sorted matches by fuzzy score. Upstream `d5aada8` replaced
> that contract: `find_order` now searches the complete authorised scope via
> `list_order_search_candidates`, keeps the helper's newest-first order, and
> returns `Order.to_public_dict()` unchanged, so `product_title` is gone. The
> transcript above is the observed record and has not been re-run. The C10
> finding does not depend on the removed key: the failure is that the agent
> picked #4455 without acknowledging that three orders matched. What the new
> contract does cost is the agent's ability to name the product from
> `find_order` alone, which is the gap worth raising separately.

### How defensible each verdict is

The handout has no answer key: the assessment is the deliverable, and a reader
judges whether it holds up against `SPEC.md`. This table is a review of the
recorded verdicts, not a second set of them. The verdicts above stand as
recorded unless they are deliberately revised.

| # | Recorded verdict | Standing | The argument to be ready for |
| --- | --- | --- | --- |
| C01 | met · SCOPE-1 | solid | See C03: the same uncited policy-derived fact was failed there |
| C02 | not met · `prompt` | solid | The refusal named no reason and cited a policy about payouts, not about the window that caused it |
| C03 | not met · `prompt` | **contestable** | ESC-1 was satisfied exactly: queued, explained, no false claim of payment. The failure rests entirely on quoting $100 without citing `cw-refunds`. Consistency with C01 has to be explained |
| C04 | met · AUTH-1 | solid | The denial came from code, and leaked nothing about the order |
| C05 | not met · `prompt` | **contestable** | The agent gave the right number, said the override wins, and cited the policy id, which is what RESP-1 asks. No requirement obliges `get_policy` over a search snippet, so `specification` fits better than `prompt`, or it is a pass |
| C06 | met · SCOPE-2 | solid | Legal advice is refused by name in SCOPE-2 |
| C07 | not met · `prompt` | solid, the strongest finding | ESC-2 is in the spec, absent from the prompt, and the conversation shows the shopper left with no ticket |
| C08 | met · RESP-3 | solid | Nothing was invented and both real alternatives were offered |
| C09 | not met · `tool` | **label contestable** | The handout defines `tool` as a function returning wrong information or changing the wrong state. `list_my_orders` returned twenty correct rows; the model then presented cancelled orders as unshipped work, which is `prompt` by that definition. The missing capability is real and still justifies the Part A tool, which the handout treats as a separate requirement |
| C10 | not met · `prompt` | solid | It committed to one order without reconciling "last week" with the dates it held, and dropped a third match |
| C11 | not met · `tool` | solid | Contract-correct matching still produced a false statement about the catalogue, so the defect is in the matching rule itself |
| C12 | not met · `prompt` | solid | The model decided the outcome from `get_order`; the tool's `not_eligible` gate never ran |

## Part A additional tool: `list_orders_by_status`

**Chosen because of C09.** A merchant asked which of their store's orders had
not shipped yet. `list_my_orders` returns the twenty most recent orders of every
status with no filter and no total, so the model did the filtering itself and
presented three *cancelled* orders as work awaiting shipment, then contradicted
itself in the closing line. That case was assessed as a `tool` failure, and a
tool-class fault is fixed in code rather than in the prompt.

Two other candidates were considered and not built: `check_refund_eligibility`
(days since delivery, the applicable window including store overrides, and the
policy id to cite), which targets the C01 and C02 citation failures, and
`get_order_details` (`get_order` plus the product title), which targets the C01
gap where the agent could not name what was ordered.

### What it does

`list_orders_by_status(ctx, status, limit=20)` in `agent/tools.py`, registered
for shopper and merchant in `TOOLS_BY_ROLE`.

- Scope is identical to `list_my_orders`: the role picks which query runs, so
  there is no argument through which a caller could reach another user's or
  another store's orders. Support is refused for the same reason as before.
- An unknown status returns `invalid_argument` naming the accepted values, so a
  typo cannot be misread as "no such orders".
- `total_matching` reports how many orders match in the caller's whole scope,
  not just how many were returned, which closes the silent truncation in
  `list_my_orders` that made "I don't see any" unsound.

### Evidence that it fixed the observed failure

Same request, same merchant, fresh session.

| | Tool calls | Response |
| --- | --- | --- |
| **Before** (C09) | `list_my_orders({})` &rarr; 20 orders, all statuses | Listed orders 5465, 3294 and 2651, all `cancelled`, as ones that "haven't shipped yet", then said nothing is awaiting shipment |
| **After** (C09b) | `list_orders_by_status({"status": "placed", "limit": 20})` &rarr; `count: 0, total_matching: 0` | "None of your store's orders are currently waiting to ship." |

Store 2 genuinely has no orders in `placed` status, so the corrected answer is
also the true one. The model selected the new tool and the right status on its
own, with no prompt change.

### Checks

| Check | Offline or live | Result |
| --- | --- | --- |
| `pytest tests/test_extra_tools.py` | offline | 8 passed — scoping, the total count, empty results, unknown status, case handling, limit clamping, support refusal |
| `pytest -q` (full suite) | offline | 117 passed, 12 skipped, 22 xfailed, 5 xpassed |
| C09b re-run | live model | tool selected and called correctly |

### Capability gaps observed

Tracked here as they appear, because Part A requires at least one additional
tool of our own, motivated by a gap seen in a real conversation.

- **No product name on an order.** `get_order` returns `product_id` with no
  title, so the agent cannot say what was ordered without a second lookup it
  has no tool for. Seen in C01.
- **Refund eligibility is asserted without the rule behind it.** The agent
  reported "refund eligible: yes" from the boolean flag, with no return window
  and no policy citation. Seen in C01.
- **No way to ask what still needs shipping.** `list_my_orders` returns twenty
  raw rows with no status filter and no signal that more exist, so the merchant
  question in C09 could not be answered properly. Assessed as a `tool` failure,
  which means the fix belongs in code. **Closed by `list_orders_by_status`; see
  the section above.**
- **Product search cannot survive a plural.** `search_products("mugs")` returns
  nothing while eleven mugs exist, because matching is substring-based by
  contract. Seen in C11, also assessed as a `tool` failure. Note that changing
  the matching rule would depart from the supplied docstring, so this needs a
  deliberate decision rather than a quiet edit.
- **Account changes are refused instead of escalated.** ESC-2 sends account
  changes of any kind to a human, but the system prompt lists credential
  changes only under "refuse" and never mentions escalation. Seen in C07.
  **This is the Part C candidate: a spec requirement missing from the prompt,
  with recorded evidence of the resulting behavior.**

### Checks run alongside

| Check | Offline or live | Result |
| --- | --- | --- |
| `pytest --runxfail tests/test_hw_holes.py -k hw1` | offline | 5 passed |
| `pytest tests/test_agent_tools.py tests/test_auth.py tests/test_eligibility.py` | offline | 24 passed |
| Twelve Part B conversations | live model | 12 captured (`gpt-5.5`); 4 met the requirement, 8 did not |
| `uv run python -m seed.generate` after C03 | offline | world restored; 573 refunds, 4455 and 4127 back to `delivered` |
