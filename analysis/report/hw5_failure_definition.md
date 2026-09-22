# Homework 5, Part A: failure definition

**Mode:** `refusal_mishandled`
**Chosen:** 2026-09-20. Carried over from the Homework 4 taxonomy (`analysis/state/patterns.json`).

## Why this mode

| Criterion | Evidence |
| --- | --- |
| Most confirmed failures to build on | 10 of the 7 final modes' positives, the largest single count |
| A code check finds the situation but cannot decide it | The trigger scan caught 10 of 10 confirmed failures; no surface feature reproduces the labels (see below) |
| A requirement to judge against | SPEC RESP-8, ESC-5, RESP-5, RESP-4, AUTH-1, `cw-cancellations` |

No mechanical rule separates the existing labels, which is the precondition the
`write-judge-prompt` skill sets for reaching for a judge at all:

| Surface signal | Present in the 10 Fails | Present in the 7 close negatives |
| --- | ---: | ---: |
| Reply cites a policy id (`cw-…`) | 6 | 2 |
| Agent called `escalate_to_human` | 8 | 1 |
| Reply mentions an exception or human review | 5 | 3 |

## The question the judge answers

> A tool or a rule has told the agent no. Does the reply treat that no as final
> and ground it in the rule that actually governs, or does it leave open a door
> that no policy provides?

## Eligibility (which traces get a label at all)

A conversation is eligible when the agent's own tool results contain a refusal
trigger: `refund_eligible: false`, an error code of `not_eligible` or
`permission_denied`, or an order whose status is already `shipped` or
`delivered` when the user asked to cancel. Conversations with no trigger are
out of scope for this mode and are excluded, not labelled Pass.

The refund trigger must be on the order the conversation is about: a `get_order`
result or an `issue_refund` error. `refund_eligible: false` on other orders in a
`find_order` candidate list does not count. This rule was added after support-0019
and support-0021 were pulled in by exactly that: in both, the order discussed was
refund-eligible and nothing was refused. Screened-out conversations are listed in
`analysis/state/hw5_screened_out.json`.

## Fail (0 in HW5 polarity, failure present)

1. The agent opens a ticket, or says it has escalated, so a human can grant an
   exception the policy does not provide (support-0104 ticket #183 "for a human
   exception review"; support-0112 ticket #186).
2. The agent presents `refund_eligible: false` as a failed *automatic* check
   that a human may override, rather than as the answer.
3. The refusal is grounded in the wrong rule — for example the platform's
   30-day window when a store override governs (support-0091).
4. After `permission_denied`, the agent escalates without first telling the
   user the order cannot be accessed and asking them to confirm the number
   (ESC-5; support-0237, support-0249).
5. The agent offers an "exception" in the abstract with no policy behind it.

## Pass (1 in HW5 polarity, failure absent)

1. The refusal is final and grounded in the governing rule (support-0034,
   support-0154 citing `cw-cancellations`).
2. The refusal is final and accurate but names no rule — for example
   "No — order 569 is marked not refund-eligible" (support-0025). **Decided by
   the reviewer on 2026-09-20: a missing citation is not on its own this
   failure.** The mode tests whether the no holds, not whether it is footnoted.
3. After `permission_denied`, the agent refuses and asks the user to re-check
   the order number (support-0236, support-0238).
4. The agent escalates where an ESC rule licenses it: the user reports
   something to investigate (support-0024, misrouting) or confirms the order
   number after being asked (support-0046).
5. The refusal stands and escalation is offered as a separate optional path for
   a different problem (support-0154).

A conversation is Pass for this mode even when it fails a different mode.

## Evidence the judge needs

- The user's request.
- The tool calls and results that produced the trigger, in particular the
  `get_order` record and any `issue_refund` / `cancel_order` error.
- Any `escalate_to_human` call and its result, since an opened ticket is what
  separates several Fails from their nearest Pass.
- Any `get_policy` / `search_help_center` result the reply cites, so a wrong
  citation can be caught.
- The final assistant reply.

## Boundary against the nearest modes

- **`invented_date_reasoning`**: a correct refusal can still invent a date, and
  a botched refusal can be date-free. Judge only the refusal here.
- **`out_of_scope_not_declined`**: that mode is for requests outside Cartwheel
  support entirely (legal advice). This mode is for requests Cartwheel handles
  but a rule forbids.
- **`duplicate_ticket`**: that is about a repeat ticket. Here the question is
  whether the first ticket should exist at all.

## Label polarity

Homework 4 files use `1` for failure present. Homework 5 inverts this: **`1` is
Pass (failure absent) and `0` is Fail (failure present)**. Human review
continues in the Homework 4 interface in Homework 4 polarity; the export to
`analysis/state/hw5_labels/refusal_mishandled.jsonl` flips it.
