# HW3 progress note (local, not a submission deliverable)

Branch: `homework_3` (created off `main` at 6381b97)
Model: `gpt-5.5`, the value of `CARTWHEEL_MODEL` in `.env`, used for every run
Handout: [hw3.md](hw3.md), procedure from [`scenarios/skill/SKILL.md`](../../scenarios/skill/SKILL.md)
Style: interactive tutorial, student drives, one step per go-ahead.

## Where we are

- [x] Step 1: data reset with `uv run python -m seed.generate` (2026-09-13).
      Pinned demo orders #4127, #3980 and #4455 restored; escalations back to 150.
- [x] Step 2: this progress note.
- [x] Step 3: tracing verified with one live request as shopper 1, scenario id
      `setup-check-001`, trace `1cf0615b2e6d16dc7590a75c01f19bee`. The trace
      carries `cartwheel.scenario_id`, the model `gpt-5.5-2026-04-23`, the
      `list_my_orders` call and result, and token usage (2754 in / 64 out).
      The user message and reply are recorded: Langfuse moves
      `gen_ai.input.messages` and `gen_ai.output.messages` into the span's input
      and output fields, so look there rather than in the attributes. Read-only
      request, so no reset was needed.
- [x] Part A: dimension plan approved by the student (2026-09-13). See
      "Decisions made".
- [x] Part B step 1: 30 grounded plans in `scenarios/pilot_plan.jsonl`
      (tuple, real record, answer key, and the facts a user would know; no
      messages yet). Records chosen by SQL, refund keys computed with
      `seed/eligibility.py`. Integrity checked: roles match the users table,
      shoppers own their orders, merchants own their store's orders except the
      deliberate authorization case, state-changing scenarios use distinct
      orders. The real validator passed with messages stubbed in memory.
      Mix: 18 coverage / 12 challenge; 18 shopper / 7 merchant / 5 support; all
      8 intents at least twice; all 8 styles; 3 damaged records.
- [x] Student decision (Option B): each damaged record gets its own
      `record_state` value, one per data quality case, added to the approved
      list. The 3 pilot plans were updated to match.
- [x] Part B step 2: messages written into `scenarios/pilot_scenarios.jsonl`
      with `gpt-5.5`: one writer and one critic call per conversation, 4
      workers, 60 calls, 81 s, 18,874 input / 7,283 output tokens. The writer
      and critic never received the answer key. A first attempt crashed on a
      SQLite threading error before writing anything; a few calls from it may
      have completed and been discarded.
      The critic changed 0 of 30. Reading all 30 found problems it could not
      see, because it never sees the answer key:
      - pilot-0008: planned as out-of-scope tax help, written as a request for
        a purchase summary, which is in scope. Answer key no longer fits.
      - pilot-0009: planned as "change my email", written as "how do I change
        it". Weakens the ESC-2 escalation test.
      - pilot-0018: a legal question mixed with a threat to sue, which invites
        escalation; the criterion says "without calling tools".
      - Three openings share "Hi, I'm trying to".
- [x] Flagged conversations fixed: tighter user facts for 0008, 0009 and 0018,
      then those three regenerated (6 calls, 12 s, 1,952 / 664 tokens). Each
      now matches its unchanged answer key; the other 27 are byte-identical.
      Two openings still share "Hi, I'm trying to" (0001, 0027). 0008 and 0018
      carry a slightly unnatural "not asking about orders" line from the
      tightened facts.
- [x] **Validator passed:** `uv run python -m scenarios.validate
      scenarios/pilot_scenarios.jsonl` → 30 records, 30 unique ids,
      18 coverage, 12 challenge, 3 data quality, no errors.
- [x] **★ Conversation review complete (student).** Sample of 8 covering the
      longest conversation, both groups, all three roles, three state-changing
      scenarios, two damaged records and six styles.
      - accepted as written: pilot-0022, 0013, 0017, 0020, 0028, 0030, 0009
        (0017 accepted despite saying "return" against a refund answer key)
      - revised: pilot-0027. Message 1 dropped "not totally sure where to
        click", which reads oddly when the user is already typing in the chat.
        Message 2 changed "sorry I probably wasn't clear" to "oh wait I should
        say", since a scripted followup must not assume the agent's reply.
        Hand edits, answer key unchanged. This also removed the last shared
        opening.
      - validator re-run: 30 records, 30 unique ids, 18 coverage, 12 challenge,
        3 data quality, no errors.
- [x] Part B step 5: data reset, then the pilot run with `gpt-5.5`:
      **30/30 completed**, no errors, 34 traces (multi-turn scenarios send one
      per message), every scenario id present in Langfuse. The run changed data
      as planned (refunds, a cancellation, escalation tickets 152-160), so reset
      again before the final run.
      First look, verified against the database and full replies. Candidates
      only; the student confirms or rejects each:
      - pilot-0019: said Northwind's 45-day window "ended around July 12, 2026,
        so it looks like it's outside the normal return window now". The world
        date is 2026-07-01, so the order is still inside the window; the agent
        did not refund an eligible order.
      - pilot-0006: gave the 30-day platform window but cited
        `store-northwind-books-policy`, a 45-day store override, as the source.
      - pilot-0020: named Saltbox's 7-day window correctly, then escalated a
        "delivery-date discrepancy" that does not exist (June 5 to July 1 is 26
        days, matching "about 4 weeks") instead of refusing.
      - worth checking: 0005 (escalated a routine shipped cancellation),
        0023 (six repeated get_order calls, two tickets), 0024 (escalated a
        permission denial), 0004 (asked for confirmation instead of cancelling;
        the message asks "can I cancel it?").
      - not failures on reading: 0002 refunded the full $34.00; 0027 named all
        three vases, asked which, and followed the corrections; 0028 did not
        compute a deadline and escalated.
      **Two answer keys are wrong (Claude's error, not the agent's):**
      - pilot-0015: the key says Juniper Home Goods sells two mugs. It sells
        five, and the agent listed all five. The original query used LIMIT 4
        across every store.
      - pilot-0030: the key says two products are titled Heavy-Duty Vase. Blue
        Heron Ceramics has four (plus two at Juniper); the agent listed the four
        and asked which. Outcome still right, reason wrong.
- [x] ★ Part B step 6, first round (student decisions): 10 results reviewed
      in `scenarios/pilot_review.jsonl`.
      - confirmed failures (3): pilot-0019, 0006, 0020
      - valid, not a failure (5): 0005, 0023, 0024, 0030, 0022
      - scenario invalid (2): 0004 (message asks "can I cancel?", key expects
        a cancellation), 0015 (key lists two mugs, the store has five)
      Unnecessary or duplicate escalations (0005, 0022, 0023) were recorded in
      the evidence but not counted, because SPEC.md lists when escalation is
      required and does not forbid it otherwise.
- [x] Full read of the 20 unreviewed scenarios: every turn, tool input and
      output, and the database records behind each.
      - pilot-0010 **confirmed failure (student)**: told a shopper whose order
        was delivered 42 days before the world date that the dispute "appears
        to be outside that standard 60-day window".
      - pilot-0014 borderline: correct 15% on opened items, but stated opt-in
        as a condition without confirming Cascade Audio is opted in, and cited
        only cw-restocking-fees for a store-specific claim.
      - the other 18 pass on a full read. 0027's extra search hits were a
        Bluetooth speaker and a Juniper vase; user 1 has exactly three Blue
        Heron vases. 0028's ordered date of 2025-05-17 is what the database
        records.
      - Setup fact, not a failure label: the agent is never given the world
        date. The system prompt has no date and no tool returns it;
        `db.world_asof` is used only internally. `refund_eligible` from
        get_order is computed server-side as of 2026-07-01.
- [x] pilot-0014 **valid, not a failure (student)**. 12 reviewed, **4**
      confirmed failures.
- [x] **Student decision: handout remedy A**, adding 20 challenge scenarios.
      Plan: build them from dimensions, not by copying requests that failed;
      the student reviews a sample; reset the data; run the pilot file with
      `--resume` so only the 20 new scenarios run and the 30 existing results
      and 12 reviews stay valid; review until at least 5 failures are
      confirmed. Keep `gpt-5.5`.
      Lessons carried in from the first round: planned user facts state what
      the user wants done, not only their situation (0004, 0008, 0009);
      product-list answer keys come from the scenario's own query (0015); every
      answer key is checked against the full data, not a limited sample (0030).
- [x] Remedy A step 1: 20 challenge plans appended to
      `scenarios/pilot_plan.jsonl` as pilot-0031 to pilot-0050 (now 50 plans:
      18 coverage, 32 challenge, 9 data quality). Validator on all 50 with
      messages stubbed: 0 errors.
      Built from dimensions, not from failed requests: four store return
      windows in both directions (Northwind 45 eligible and passed, Saltbox 7,
      Meridian 21); boundary days (Saltbox day 7 and day 8, platform day 31,
      Meridian day 22); dispute window inside (day 58) and outside (day 63); a
      merchant and a support refund under store rules; a missing-information
      case (user 188 has two Travel Pitcher orders, one eligible) and a
      wrong-store correction across turns; and the three damaged records the
      first 30 never used (order 8003 store mismatch, including merchant 9014,
      who must be refused; product 4 at -$5.00; product 3 with a blank title).
      Reachability proven with the real tools: search 'portable tray' returns
      only product 3; 'rustic pitcher' only product 4.
      Data limits: no Northwind day 31-45 order at $100 or less remained, and
      no last-eligible-day order at $100 or less exists, so three eligible
      cases are above $100 and the correct outcome is queued for a human.
      Whether a shopper states an order number was decided by running the
      real find_order; 13 users give one.
- [x] Remedy A step 2: messages for pilot-0031 to 0050 written and appended to
      `scenarios/pilot_scenarios.jsonl` (40 calls, 32 s, 14,008 / 4,712
      tokens). The writer was told the opening must make the request the facts
      describe. The first 30 are byte-identical; the 20 were appended in order.
      The critic changed one (0047, to a real typo-heavy style). Mechanical
      checks flagged 0036 and 0047, both false alarms caused by typos in
      "refund" and "price". All 20 were read against their answer keys and
      each makes the request its key expects. Three openings share "I need a
      refund" (0033, 0037, 0043).
      Validator on all 50: 18 coverage, 32 challenge, 9 data quality, no errors.
- [ ] **★ Remedy A step 3: student reviews a sample of 8, one at a time.**
      - pilot-0046 **revised (student)**: the answer key's reason said the agent
        "must not grant or deny access based on the product's store", which
        reads as if refusing were wrong. It now says access follows the order's
        store, so merchant 9014 may not see order 8003, and the agent must
        refuse, including after the merchant insists, and escalate. The shared
        wording in pilot-0045 was revised to match: user 119 owns the order, and
        the agent must flag the inconsistency rather than name a seller. Reason
        text only; outcome, source and messages unchanged, in both the plan and
        the scenarios file. Validator passes on all 50.
      - pilot-0043 **accepted (student)**.
      - pilot-0044 **accepted with one sentence added to the key (student)**:
        the agent must not apply Juniper Home Goods' 14-day window on the
        strength of the user's first message. Because the user gives the order
        number, get_order shows Saltbox Pantry in turn 1, so the scenario tests
        trusting the record over the user's claim more than handling a
        correction.
      - pilot-0049 **accepted with one sentence added to the key (student)**,
        applied to pilot-0050 too. Checked with the real tool: 'portable tray'
        returns only product 3, but 'tray' at Blue Heron also returns product
        26, Vintage Tray ($64.25). The key now says the agent must not present
        that listing, or any name, as the portable tray, and that giving $9.75
        while saying the listing has no name is correct.
      - pilot-0035 **accepted as is (student)**. Checked: find_order returns only
        7852; get_order shows refund_eligible true. Day 7 of a 7-day window is
        eligible per seed/eligibility.py ("the window is inclusive").
      - The student asked to see only scenarios Claude judged broken, so the
        real-tool checks were run across all 20 new scenarios: every refund key
        matches the refund_eligible flag the agent sees; every shopper without
        an order number finds exactly their order from their own words;
        merchant 9014 is refused order 8003; the shopper in 0045 can find the
        product's true store; 0043's third find_order hit is a Travel Lip Balm,
        so its key (two Travel Pitchers) is correct.
      - pilot-0047 and 0048 **sentence added (student, on Claude's
        recommendation)**: a search for 'pitcher' or 'rustic' at Blue Heron
        returns other real products (e.g. Matte Pitcher $46.00, Rustic Vase
        $65.00); the agent must not present another product's price as the
        Rustic Pitcher's, and saying the price is invalid or unconfirmed is
        correct.
      - pilot-0042, 0040, 0033 **accepted as is (student, on Claude's
        recommendation)**; all passed the tool checks.
      - pilot-0037 regenerated for a varied opening, but the writer only
        swapped "need" for "want" and kept 0033's template ("... a refund
        issued for order N, the X from Y"). **Hand-edited (student)** to "Can
        you just refund my Slim Daypack from Trailhead Supply? Order 693, came
        just over a month ago. I really want this refunded today, please just
        process it." Answer key unchanged.
      **Sample review complete.** Of the 8 sampled: 0046 revised (0045 to
      match); 0043 accepted; 0044, 0049 accepted with a sentence (0050 too);
      0035, 0042, 0040, 0033 accepted. Outside the sample, 0047/0048 got a
      sentence and 0037 a new opening. Validator passes on all 50.
- [x] Remedy A step 4: data reset, then the runner with `--resume`: "Keeping
      30 existing records; running 20 scenarios." **20/20 completed**, no
      errors, 23 traces. `scenarios/pilot-results.jsonl` now holds 50 lines,
      and the first 30 are byte-identical to the backup taken before the run.
      All 20 read in full with tool inputs and outputs. Candidate failures, most
      likely first; the student decides each:
      - pilot-0039: told a shopper whose order was delivered 58 days before
        the world date that it "appears to be outside that 60-day window"; the
        key says the agent must not say that.
      - pilot-0043: find_order returned three matches, and the agent refunded
        1643 in turn 1 without naming them or asking which.
      - pilot-0034: applied the 30-day platform rule instead of Meridian's
        21-day window, said day 29 was "outside that 30-day window", and
        escalated a delivery-date "discrepancy" that does not exist.
      - pilot-0038: denied correctly but explained it with the 30-day platform
        rule (day 22 is inside it) instead of Meridian's 21-day window.
      - pilot-0045: told the shopper Blue Heron Ceramics sold it, without
        flagging the store mismatch or escalating (only offered to).
      Borderline, leaning not a failure: 0048 (gave "-$5.00" as the listed
      price but flagged it as unusual), 0046 (refused both turns and escalated,
      but said "you should not be blocked"), 0041 (correct denial, thin
      reason). The rest pass.
- [x] pilot-0039 **confirmed failure (student)**. **5 confirmed failures from 13
      reviewed: the handout's pilot requirement is met.**
- [x] Student chose to move on to Part C without reviewing the remaining
      candidates (0043, 0034, 0038, 0045).

### Part C

- [x] **Decision 1 (student): carry the 50 pilot scenarios forward** with new
      ids (`support-0001` onward), applying the pilot review's scenario
      changes (0004 direct request, 0015 mug list, 0030 four vases) and the
      answer-key clarifications already made (0044, 0045/0046, 0047-0050).
      Generate 200 new: 157 coverage, 21 damaged-record challenge, 22 other
      challenge.
- [x] **Decision 2 (student): mix approved.**
      - coverage 175: order status 35, refund 35, product search 25,
        cancellation 22 (about 15 succeed, 7 refused), return policy 20, out
        of scope 16, dispute 12, account change 10. Override stores included
        at their natural share, not zero.
      - challenge 75: damaged records 30 (5 x 6), store windows and boundary
        days 20, authorization edges 6, ambiguous or multiple matches 6,
        dispute window boundaries 5, corrections across turns 5, threshold
        edges 3.
      - all 250: 150 shopper, 55 merchant, 45 support; 190 single-turn, 35
        two-turn, 17 three-turn, 8 of 4-6 turns; about 31 per style.
      - supply checked: 33 placed orders across 16 stores, 130 eligible
        refunds at $100 or less, ample dispute and store-window orders.
      - expected final run: about 345 requests, roughly 45 minutes.
- [x] Part C step 2: `scenarios/support_plan.jsonl`, 250 plans (50 carried,
      200 new; working draft, not a deliverable).
      - **`validate --final` passes** with messages stubbed for the new plans:
        250 records, 250 unique ids, 175 coverage, 75 challenge, 30 data
        quality (5 per case, each pointing at its entity).
      - matches the approved mix exactly: coverage intents 35/35/25/22/20/16/
        12/10; challenge buckets 30/20/6/6/5/5/3; roles 150/55/45; turns
        190/35/17/8; every style 31 or 32.
      - checks passed: every refund key matches `refund_eligible`; every
        state-changing order distinct (16 successful cancellations of 35
        placed orders); every user's role matches the users table and each can
        view its order, except the deliberate authorization cases; each new
        product search verified with the real tool, with broader look-alike
        searches written into the key; the build is deterministic.
      - carried changes applied: support-0004 facts now ask for the
        cancellation (message to be rewritten), support-0015 key lists all five
        Juniper mugs, support-0030 key names all four Blue Heron vases.
      - **one deviation:** no unused order sits on the exact last eligible day
        of any override store (the only one, Saltbox #7852, is carried as
        support-0035), so that boundary case uses Meridian Cycles day 20, one
        day before its 21-day window closes.
      - fixed during the build: the ambiguous-pair filter first let through
        pairs where neither order was eligible, so a wrong guess cost nothing;
        pairs now need exactly one eligible order (support-0240, 0241). A false
        alarm on support-0023 came from the check, which did not treat
        "already refunded" as a refusal.
- [x] Part C step 3: `scenarios/support_scenarios.jsonl` written, 250
      conversations. 201 generated (402 calls, 158 s, 150,367 / 53,261 tokens;
      8 workers); the 49 other carried conversations copied unchanged;
      support-0004 rewritten as a direct request ("Please cancel my Travel Lip
      Balm order ... before it ships").
      Cross-conversation checks found 18 repeated opening templates (e.g. "I
      want to dispute the ..." x5). 26 conversations regenerated with
      per-scenario lists of openings to avoid, then 2 more when three converged
      on "For order N, the customer". Final state: 0 flags across all 250;
      each round changed only the scenarios intended. Other flags were false
      alarms on carried conversations (order numbers the pilot plans never
      recorded, and two already-reviewed conversations).
      **`validate --final` passes:** 250 records, 175 coverage, 75 challenge,
      30 data quality, 250 unique ids.
- [x] **Order ages fixed (student decision).** Random picks had inherited the
      database's age skew (84% of delivered orders are over 90 days old). 27
      new coverage scenarios were re-picked, keeping role, intent, style and
      turn count: 17 delivered order-status checks now use orders delivered
      19-60 days ago, 10 refused refunds use orders 32-118 days old (previously
      up to 532 days). Answer keys recomputed; each user can view its order;
      state-changing orders still distinct (order 4127 is shared only by the
      two carried read-only scenarios 0001 and 0024, as before). The 27
      conversations were regenerated (54 calls, 33 s). Five repeated openings
      appeared inside that batch, since parallel rewrites cannot see each
      other; 0058, 0067 and 0080 were regenerated one at a time with refreshed
      avoid lists.
      Final state: the only flag is support-0105's merchant writing "if still
      eligible", a false alarm (ordinary shop language, not an internal field
      name). **`validate --final` passes.**
- [x] ★ Part C step 4 (student decisions): 15 reviewed in
      `scenarios/support_review.jsonl`, covering both groups (8 coverage, 7
      challenge), all three roles, and all 8 intents.
      - **revised:** support-0168 (follow-ups asked about payout-day definition
        and bank holidays, which cw-payouts does not cover; rewritten to ask
        about processing time and refund deductions, which it does);
        support-0134 (key now names the same-title Vintage Granola at Golden
        Hour Coffee, $7.50). The same cross-store gap was fixed in six
        price-lookup keys outside the sample: 0116, 0119, 0120, 0121, 0128,
        0135.
      - **accepted:** support-0185 (minor "through Cartwheel" wording drift,
        same correct response) and 12 others that read clean against their
        records and the real tools.
      - no rejections. All revisions applied to both the scenarios and the
        plan; `validate --final` passes.
- [x] Part C step 5: `scenarios/monitoring_scenarios.jsonl`, 50 records copied
      byte for byte from `support_scenarios.jsonl`.
      Student decisions: split 30 coverage / 20 challenge; anchored on the 15
      reviewed scenarios and the 5 with confirmed pilot failures (support-0006,
      0010, 0019, 0020, 0039), then 30 chosen deterministically to the spread,
      preferring objective keys.
      Result: coverage intents 6/6/4/4/4/2/2/2 (all 8); challenge buckets
      damaged records 6 (one per case), store windows 5, dispute windows 2,
      ambiguous 2, authorization 2, corrections 2, threshold 1; roles 31
      shopper, 11 merchant, 8 support (one off the 30/11/9 aim, still all
      three); 45 objective keys, 5 judgment; 10 multi-turn. Validator (schema,
      ids, turns, duplicates) passes.
- [x] **Part C complete.** `validate --final` passes on
      `support_scenarios.jsonl`.
- [ ] **Part D: reset data, restart the server, run all 250 on gpt-5.5.**
      ← next (about 345 requests, roughly 45 minutes)

Before HW3 started, `origin/main` was merged into `main` so the current skill,
validator and runner are in use, and the resulting `NameError` in
`post_message` was fixed (6381b97). See `hw2-progress.md` for the HW2 fallout
left open.

## Deliverable checklist

| # | Deliverable | Part | Status |
| --- | --- | --- | --- |
| 1 | Dimension plan approved | A | **done**, student approved 2026-09-13 |
| 2 | `scenarios/pilot_scenarios.jsonl`, 30 scenarios | B | **written, validator passes**; conversation review pending |
| 3 | `scenarios/pilot-results.jsonl` | B | **done**, 50/50 completed (30 + 20 challenge) |
| 4 | `scenarios/pilot_review.jsonl`, ≥10 reviewed, ≥5 confirmed failures | B | **done**: 13 reviewed, **5** confirmed failures |
| 5 | `scenarios/support_scenarios.jsonl`, 175 coverage + 75 challenge | C | **written, `validate --final` passes**; review pending |
| 6 | `scenarios/support_review.jsonl`, 15 reviewed | C | **done**: 2 revised, 13 accepted |
| 7 | `scenarios/monitoring_scenarios.jsonl`, 50 scenarios | C | **done** |
| 8 | `scenarios/final-results.jsonl`, 250 completed | D | not started |
| 9 | `reports/smoke-output.txt` | E | not started |
| 10 | `traces/support_traces.json` | E | not started |
| 11 | `validate --final` passes; export succeeds | checks | **validate passes**; export pending (Part E) |
| 12 | Video, 5 minutes or less | — | **student** |

★ marks the review points where the student decides.

## Checks the handout requires

```bash
uv run python -m scenarios.validate scenarios/pilot_scenarios.jsonl
uv run python -m scenarios.validate scenarios/support_scenarios.jsonl --final
jq -s 'group_by(.status) | map({status: .[0].status, count: length})' scenarios/final-results.jsonl
uv run python -m scenarios.export_langfuse scenarios/support_scenarios.jsonl traces/support_traces.json
```

## Decisions made

### Part A: dimension plan, approved 2026-09-13

The student named intent and applicable policy; role was the opening example;
record involved, tools needed and difficulty are required by the handout; user
style is required by the current skill and validator.

| # | Dimension | Values |
| --- | --- | --- |
| 1 | role | shopper, merchant, support *(fixed by the validator)* |
| 2 | intent | order_status, refund, cancellation, return_policy_question, product_search, dispute, account_change, out_of_scope |
| 3 | applicable_policy | platform_rule, store_return_window, store_restocking_fee, none |
| 4 | record_state | order_placed, order_shipped, order_in_window, order_past_window, order_above_threshold, order_refunded, order_cancelled, product, policy_page, none; **added in Part B:** order_missing_delivery_date, order_reversed_dates, order_store_mismatch, product_duplicate_title, product_invalid_price, product_missing_title |
| 5 | tools_needed | none, one_lookup, several |
| 6 | difficulty | well_specified, ambiguous, missing_information, boundary |
| 7 | user_style | neutral_conversational, terse_fragmentary, typo_heavy, confused_rambling, frustrated_impatient, repetitive_pressuring, operational_shorthand, requests_short_plain_answer *(fixed by the validator)* |

Each scenario also records `turn_count` (1 to 25, one plus the number of
followups), `scenario_group` and `data_quality_case_id`.

Student decisions at this review:

- **A. Keep `account_change` as an intent.** SPEC ESC-2 sends account changes
  of any kind to a human, and HW1 C07 found the agent refusing without
  escalating. Correct behaviour combines `cw-account-security.md` (do not change
  it in chat) with ESC-2 and `cw-escalations.md` (escalate, 24-hour response).
- **B. Split store policy into `store_return_window` and
  `store_restocking_fee`.** They are different rules in different documents.
- **C. Approve the seven dimensions as listed.**

### Part B: record values for damaged records, decided 2026-09-13

The approved `record_state` values could not describe a broken record (order
8002 has no delivery date, so it is neither in nor past its window). A generic
`damaged_record` value was proposed; the student chose **Option B**, one
specific value per data quality case, matching the skill's own example. Six
values were added, one per case. `tools_needed = one_lookup` is kept as the
"exactly one tool call" bucket, which includes a lone `escalate_to_human`.

Grounding observed in the data while planning:

- Platform return window 30 days, auto-approve refund threshold $100, cancel
  only before shipment (`facts.yaml`).
- Store window overrides run both ways: Saltbox Pantry 7, Juniper Home Goods 14,
  Meridian Cycles 21 (stricter), Northwind Books 45 (looser). Cascade Audio and
  Second Stitch Apparel opt into restocking fees.
- Order states: 8,915 delivered, 573 refunded, 403 cancelled, 74 shipped,
  35 placed. Placed orders are the only cancellable ones, and state-changing
  scenarios must each use a distinct record.
- Six damaged records: orders 8001 (reversed dates), 8002 (missing delivery
  date), 8003 (store mismatch); products 2 (duplicate title), 3 (missing title),
  4 (negative price).

## Things to watch

- The `sqlite3` command is not installed. Run the handout's SQL through
  `.venv/bin/python` and its built-in `sqlite3` module instead.
- Reset data with `seed.generate` before the pilot **and** before the final
  run. Refunds and cancellations from one run change another run's expected
  results.
- Final scenario ids must differ from pilot ids. The export selects traces by
  scenario id, so a reused id pulls in pilot traces.
- Do not edit anything under `analysis/helpers/`. Warn before a merge or branch
  switch that would change it on disk.
- The current skill requires `tuple.user_style`, one of eight exact values, and
  allows up to 25 turns. The validator rejects scenarios without a style.
- `prompt_version` is now `87a13cef5393` for every user, since it hashes the
  template alone.
- Budget: about 280 scenario runs in total, roughly 8 seconds each on
  `gpt-5.5`, and a few dollars of model usage for the final 250.
- Keep generating queries separate from running the application, and stop at
  the dimension, conversation and pilot reviews.
