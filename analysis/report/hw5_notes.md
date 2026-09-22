# Homework 5 working notes: `refusal_mishandled`

A running record of what was done and decided, part by part. The failure
definition is in `hw5_failure_definition.md`.

## Part A: labels

- **Mode.** `refusal_mishandled`, chosen for the most Homework 4 positives (10)
  and a code trigger that caught all of them. No surface feature (a policy
  citation, an escalation call, the word "exception") reproduces the labels.
- **Boundary decisions by the reviewer.** A correct refusal that names no rule
  is Pass (support-0025). Opening an exception ticket is Fail; only offering one
  is Pass (support-0020 vs support-0105). A dispute past the 60-day window that
  is escalated anyway is Fail (support-0040, -0245); one inside the window is
  Pass (support-0190). Telling the user a window has closed when it has not is
  Fail even if a ticket is opened (support-0192, -0191). A reply grounded in a
  rule that does not govern the request is Fail (support-0188, hw5-0016).
- **Judge input decision.** The traces never state the current date, so each
  judge input carries a fixed reference block: the session date (2026-07-01)
  and the return, dispute, cancellation and refund rules, quoted from
  `data/policies/`.
- **Sources.** 57 conversations from the Module 1 export (every eligible one),
  plus 20 generated scenarios (`scenarios/hw5_scenarios.jsonl`) run through
  Cartwheel on gpt-5.5 with the same prompt version (87a13cef5393), because the
  export had no unlabelled eligible conversations left. Generation cost $1.32.
  Sixteen generated messages were hand-edited to restore their assigned styles
  and remove details that would change the expected behaviour; every draft is
  kept in `scenarios/hw5_scenarios_provenance.json`.
- **Screened out.** support-0160, -0019 and -0021 matched the trigger scan but
  nothing was refused (`analysis/state/hw5_screened_out.json`).
- **Result.** 77 labelled conversations, 40 Pass and 37 Fail, in
  `analysis/state/hw5_labels/refusal_mishandled.jsonl` (1 = Pass).
- **Who decided.** 54 labels are proposals from the coding agent that the
  reviewer accepted, 21 were set by hand, and 2 came from Homework 4 rules the
  reviewer approved. The reviewer rejected and relabelled every contested case.
- **Side finding.** The taxonomy had no retrieval mode. A candidate,
  `governing_policy_not_retrieved`, is recorded in `patterns.json`.

## Part B: inputs and split

- **Inputs.** `analysis/run_judges.py prepare` writes
  `analysis/state/hw5_trace_inputs.json`: one record per conversation with the
  context block, every earlier turn, and the labelled turn's tool calls, tool
  results and final reply. Tool calls render as `get_order({...})` because the
  shared renderer drops tool names. A check rejects any record containing the
  mode name, review wording, a scenario id, or an expected-outcome code, and
  confirms each record ends with the agent's reply.
- **Close variants removed.** Nine conversations came from three Homework 3
  data-quality groups (orders 8001, 8002, 8003). Following the handout ("keep
  one record from each group of duplicate runs or close scenario variants"),
  the lowest scenario id in each group was kept, without looking at labels.
  Dropped: support-0208, -0210, -0211 (kept -0028); -0212, -0214 (kept -0029);
  -0222 (kept -0046). Five of the six were Pass and one Fail.
- **Split.** Found only after the first split had been written, before any
  prompt example was chosen or any judge run, so the unused split was removed
  and rebuilt once. `split_labels`, fractions 0.20/0.40/0.40, seed 7,
  `min_per_class=10`, over the 71 remaining records:

  | Split | Pass | Fail | Total |
  | --- | ---: | ---: | ---: |
  | Train | 7 | 7 | 14 |
  | Dev | 14 | 14 | 28 |
  | Test | 14 | 15 | 29 |

  No order appears in more than one conversation. `splits.json` stays unchanged
  from here on.
- **Checks.** Offline test suite: 169 passed, 1 pre-existing failure
  (`test_m2_run_judge_persists_store_predictions_for_prevalence`, failing before
  Homework 5). No model was called in Part B.
