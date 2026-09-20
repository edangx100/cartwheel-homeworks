# Homework 4: review summary

Cartwheel support agent, Module 1 traces. Human trace review and failure
taxonomy. Written 2026-09-20.

All judgments in this report are the reviewer's. Claude drew samples, ran
searches and drafted proposals; every trace entering the taxonomy was read and
ruled on by the reviewer before it counted.

---

## 1. The reviewed sample

**110 distinct traces**, in seven batches:

| Batch | Traces | How they were chosen |
| --- | ---: | --- |
| `initial_uniform` | 15 | uniform random (seed 7) |
| `initial_cluster` | 15 | k-means cluster representatives |
| `dimension` | 30 | stratified across **role** (10 shopper, 10 merchant, 10 support), chosen before any outcome was seen |
| `depth` | 25 | depth searches for candidate modes and close negatives |
| `final_uniform` | 15 | uniform random stability check, drawn after the taxonomy was drafted |
| `depth_partd` | 7 | Part D searches for more instances of one mode |
| `part_a` | 3 | reviewed in the standard Langfuse view before the review app existed |
| **Total** | **110** | |

The first five batches are the 100 the handout asks for; no trace counts
toward more than one. The last two were added afterwards and are reported
separately:

- **`depth_partd`** — the Part D search for additional instances of
  `inconsistent_record_not_flagged` returned 11 traces, 4 already placed. The
  reviewer read the other 7 and accepted all 7. They joined the review set so
  Part E could label them; without them two of that mode's positives would
  carry no label.
- **`part_a`** — `support-0246`, `support-0242` and `support-0249`, each the
  founding observation of a final mode. Their open codes are less detailed
  than later ones, because they were written while reading raw JSON in the
  standard Langfuse view.

**Coverage.** 126 annotations: 70 "no failure observed", 52 failure notes, and
4 superseded marks kept in history. 182 AI suggestions were decided, 179
accepted and 3 rejected.

**The sample is deliberately not representative.** Clustering, stratification
by role and repeated depth searches all steer it toward failures. The numbers
in section 2 are therefore **sample fractions, not prevalence estimates**.
Homework 5 estimates prevalence against the full Module 1 trace store.

---

## 2. The final taxonomy, applied

Seven binary modes, each applied to all 110 traces: **770 judgments**, every one
written to `analysis/state/labels/` and to Langfuse as a numeric score named
after the mode. All 770 scores were read back from Langfuse and verified.

| Mode | Present | Sample fraction | Evaluator | Requirement |
| --- | ---: | ---: | --- | --- |
| `refusal_mishandled` | 10 | 9.1% | code check + LLM judge | RESP-5, RESP-8, ESC-5, AUTH-1 |
| `invented_date_reasoning` | 8 | 7.3% | LLM judge | RESP-9, RESP-3 |
| `user_claim_not_reconciled` | 6 | 5.5% | LLM judge | RESP-6 |
| `duplicate_ticket` | 5 | 4.5% | code check | ESC-6 |
| `inconsistent_record_not_flagged` | 5 | 4.5% | code check + LLM judge | RESP-3, dq-order-reversed-dates |
| `out_of_scope_not_declined` | 4 | 3.6% | code check | SCOPE-2 |
| `write_on_unconfirmed_target` | 3 | 2.7% | LLM judge | RESP-7 |

**Modes per trace:** 72 traces carry none, 35 carry one, 3 carry two. A trace is
allowed more than one mode; `support-0045` is the clearest case, carrying both
`user_claim_not_reconciled` and `inconsistent_record_not_flagged`.

**Three groups were considered and rejected**, kept in `patterns.json` with
status `rejected` so the reasoning stays inspectable:

| Rejected group | Why |
| --- | --- |
| `goal_not_reclarified` | one example after batch 1 and none after; the 5 depth picks for unclear requests were fine or a different failure |
| `permission_denied_escalated_without_confirming` | merged into `refusal_mishandled`: only 4 traces in 350 had a `permission_denied`, 2 of them fine, and one refusal rule corrects both |
| `product_record_defect_not_flagged` | 16 traces surface broken product records, but only 4 are inside the sample and the reviewer had read all 4 and found no failure. One unreviewed trace does not support a mode |

---

## 3. Stability: the final 15 traces

The `final_uniform` batch was drawn uniformly at random after the taxonomy was
drafted, to test whether new kinds of failure were still appearing.

**Three of the 15 contained a failure. All three fell into modes that already
existed. Zero new consequential modes appeared.**

| Trace | Mode |
| --- | --- |
| `b1078d05` | `duplicate_ticket` |
| `79a39154` | `invented_date_reasoning` |
| `c813107b` | `inconsistent_record_not_flagged` |

On that basis the taxonomy was treated as reasonably stable and no further
batch was drawn. Part C supports the same conclusion from a different
direction: eight scenarios replayed against a live model through Raindrop
Workshop produced **no behaviour outside the taxonomy**.

---

## 4. One taxonomy revision, in full

**Two groups became one: `refusal_mishandled`.**

After batch 1 there were two separate candidates, plus a stray observation:

```
  ineligible_refund_mishandled              7 examples
  permission_denied_escalated_…             2 examples
  support-0005 (cancel on a shipped order)  1 example
```

The permission group could not reach the three examples a mode requires: only
**4 traces in all 350** ever produced a `permission_denied`, and in 2 of them
the agent behaved correctly.

The merge test the handout gives is *would one product change fix both?* Here
it would. All three are the same shape — a rule or a tool result says no, and
the agent fails to say no clearly:

```
  refund not eligible  ─┐
  order already shipped ─┼──▶  one refusal rule fixes all three:
  no permission for it ─┘      say no, name the governing rule, give the next
                               step, and open a ticket only when an escalation
                               rule lists the case
```

The three merged into `refusal_mishandled`, now the largest mode at 10
positives. The absorbed group is kept with status `rejected` and a note
recording where it went.

**A second revision worth recording: a mode was renamed.** After the taxonomy
stabilised it was compared with the AgentErrorTaxonomy (arXiv 2509.25370).
That comparison exposed that `out_of_scope_escalated` described only 1 of its
4 examples — the other three call a tool (`search_help_center`,
`list_my_orders`, `get_policy`) without opening any ticket. The definition had
always been broader than the name. It was renamed
**`out_of_scope_not_declined`**. No examples moved.

The comparison also surfaced two categories the published taxonomy has and this
one does not — *parameter error* and *inefficient plan*. Both were declined:
the parameter cases were already judged a tool-contract ambiguity and the agent
recovered, and Cartwheel's specification has no efficiency requirement to
violate.

---

## 5. Revisions to SPEC.md

Six requirements were added, each written **before** any failure was counted
against it, and each recorded in a new revision-history section in `SPEC.md`
naming the annotation that motivated it.

| New rule | What it requires | Motivating annotation | Mode |
| --- | --- | --- | --- |
| **RESP-6** | Do not present user-supplied details as verified order data | `partA-2` (`support-0246`) | `user_claim_not_reconciled` |
| **RESP-7** | Before a refund or cancel, ask if the target is not pinned to one candidate | `partA-3` (`support-0242`) | `write_on_unconfirmed_target` |
| **RESP-8** | When `refund_eligible` is false, say so and why; no unsupported exception path | `amu7z2qna1fxc` (order 554, ticket #163) | `refusal_mishandled` |
| **RESP-9** | The session context states the current date; elapsed time only from it and tool dates | `amu87uosjic75`, `amu8grxazwx04` | `invented_date_reasoning` |
| **ESC-5** | After `permission_denied`, ask the user to confirm the order number before escalating | `partA-5` (`support-0249`) | `refusal_mishandled` |
| **ESC-6** | Refer to an open ticket for the same issue instead of opening another | `amu7wji3zst4g` (tickets #155/#156) | `duplicate_ticket` |

Editing the specification does not change the running application: the rules
reach the agent through the system prompt, the tool code and the authorization
layer. None of the recorded failures is affected by these additions.

**RESP-9 is the one that needs a code change, not just wording.** Every scenario
is set on 2026-07-01, but the session context the server injects carries only
role, user id and store id — no date. With nothing to work from the agent
supplies its own, and in two traces it used **2026-09-14**, the day the Module 1
traces were recorded, telling the user an order was outside a window it was
58 days inside. Implementing it is outside Homework 4; the rule is recorded so
the failures have a requirement to cite.

One further draft revision is recorded as still pending: a dispute that appears
to fall outside the `cw-disputes` window should be reported as likely
ineligible, with the policy cited, and still escalated. No mode depends on it.

---

## 6. Searches, and one rejected suggestion

Two searches were run for additional instances of `inconsistent_record_not_flagged`,
the second after the definition was revised.

**The repeat search was not a formality.** The first filter could only detect an
order/store mismatch when the agent had itself looked the product up, so it was
structurally blind to the traces where *not looking* was the failure. The
second compared each order against the seed catalogue directly and found traces
the first pass could never have returned.

Of 3 rejected suggestions across the assignment, the one that draws a boundary
is **`support-0222`**. The search proposed it as a positive; the reviewer
rejected it. Order 8003 is the same broken record as `support-0221`, and both
agents did one lookup and never mentioned the mismatch. The difference is what
was asked:

```
  support-0221  "which store handles this?"   ──▶  POSITIVE
                the question turns on the broken relationship

  support-0222  "please refund order 8003"    ──▶  REJECTED
                a refund request, and the reply never names a store as seller
```

The rule that separates them is now written into the mode's boundary: the agent
owes a second lookup when the request **turns on** the relationship, not on
every routine lookup. Without that line the mode would demand the agent audit
every field of every record it reads.

The other two rejections were a suggestion the reviewer disagreed with
(`support-0189` turn 4, where Claude proposed "no failure" and the reviewer
found one) and a duplicate (`support-0002`).

---

## 7. Corrections made during review

Two are worth recording, because both changed the taxonomy.

**A positive was withdrawn.** `support-0234` had been a positive for
`user_claim_not_reconciled`, on a note reading "the user said delivered today
but the record says 2026-07-01". On a re-read the reviewer found no failure:
2026-07-01 *is* the date every scenario is set on, so the user's claim and the
record agree. Neither clause of the mode fires. The note is now "no failure
observed", with the original wording kept in its history. Worth noting that
this is the same error the taxonomy names in `invented_date_reasoning` —
reading a date without anchoring to what "today" is.

**A boundary was then decided, and eight traces re-examined.** Withdrawing that
positive left the mode with two, one short of the minimum, so a search looked
for a replacement. It found **12 traces inside the sample** with the
`support-0246` pattern: the reply lists an item name among verified order
fields, although `get_order` returns no title and `search_products` was never
called. All 12 had been marked "no failure observed".

The reviewer decided the rule once rather than trace by trace: this is a
failure **only when the unverified detail reaches a refund, a cancellation or a
ticket** — when it is written into a record or put in front of a human. That
added 4 positives and left the other 8 as close negatives on exactly that line.
The boundary now states it, so a second reviewer draws it in the same place.

---

## 8. Checks

| Check | Method | Live model? |
| --- | --- | --- |
| Full test suite | `uv run pytest` — 169 passed, 1 pre-existing unrelated failure | no |
| 770 scores written to Langfuse | app sync, deterministic score ids | no |
| Scores verified | 12 sampled read back from Langfuse by id, 12/12 match; 0 local-vs-ledger disagreements across all 770 | no |
| Part C replays | 8 Module 1 scenarios replayed through the server into local Workshop | **yes**, 11 turns with `gpt-5.5` |

Only Part C called a language model. Everything else reads recordings Module 1
already made.

---

## 9. Ready for Homework 5

Homework 5 needs at least 30 Pass and 30 Fail labels per mode. **No mode reaches
30 Fail**; the largest is `refusal_mishandled` at 10. Pass labels are plentiful
(100 or more per mode). Every mode will therefore need synthetic scenarios
targeting it before a judge can be split and validated, which the handout
anticipates.

Two modes deserve care there:

- **`inconsistent_record_not_flagged`** rests entirely on three seeded bad
  orders (8001, 8002, 8003) across 14 traces. Its positives are not a sample of
  a large population; they are close to the whole population.
- **`invented_date_reasoning`** is intermittent. `support-0114` passed in
  Module 1 and failed when replayed on identical data, so a judge trained on it
  is learning a behaviour the agent shows only sometimes.
