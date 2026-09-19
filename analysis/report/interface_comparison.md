<!-- DRAFT written by Claude from my Part A notes (part_a_langfuse_review.md). Edit into my own words, then delete this line. -->

# Interface comparison

My review interface is in `analysis/review_app/`. I compared it with the reference interface (`analysis/server.py`, `analysis/ui/index.html`) and with the standard Langfuse trace view, where I reviewed five traces first (`part_a_langfuse_review.md`).

## Retained from the reference interface: notes in the margin beside the evidence

I kept the reference's way of annotating. I select text anywhere in a trace, write a free-form note in a popover, and the note appears in a right-hand margin next to the highlighted text. Hovering over either one outlines the other. I kept it because an open code has to point at its evidence. In Langfuse I had to copy text out of the JSON to say what I meant, and here the note stays attached to the exact words, whether that's a reply sentence, a tool argument, or a field in a tool result.

## Changed after inspecting my traces: whole conversations, in order, with readable tool steps

The reference shows one record at a time. Cartwheel records one trace per user turn, so a multi-turn conversation turns into unrelated traces. In Langfuse I couldn't tell which turn of how many a trace was, and finding the other turns by hand was error-prone. This happened in all three multi-turn traces I reviewed (`support-0248`, `support-0242`, `support-0249`). In each of them I couldn't judge turn 2 without turn 1: in `support-0249`, the ticket opened in turn 1 matters only because turn 2 corrects the order number.

My interface shows each session as one page, with its turns in timestamp order and every turn labelled with its trace ID. Labels and Langfuse scores still attach to the individual trace.

My traces had no `cartwheel.session_id`, because the server never records it on the trace. So sessions are recovered from the server's session store, by matching each trace's user message to the stored message with the nearest timestamp. All 350 traces matched, with exactly one session per scenario. The matches are saved in `analysis/state/session_map.json`.

The same inspection led to a second change. In Langfuse I had to read nested JSON to follow the agent's reasoning and tool results (`support-0246`, `support-0234`). Each step is now drawn as a block:
- the agent's narration, marked "not shown to user";
- the tool call, with its kind: lookup, retrieval, or write;
- the result, with a one-line status such as `permission denied`, `auto_approved`, or `ticket 238`.

The system prompt and tool schemas are shown once per session instead of on every model call.

## Changed during review: a live count of reviewed traces

Halfway through batch 1 I was counting reviewed traces by hand to know how far I had got. The reference only shows progress in a separate view, and my first version only had a small count at the foot of the session list. I added a counter to the top bar that is always visible and updates as soon as a note or mark is saved. It shows reviewed traces out of the sample, split into:
- traces marked with a first failure;
- traces marked "no failure observed";
- traces with notes but no final mark yet;
- traces not yet opened.

Hovering shows the same counts per batch, and clicking opens the Progress view. It also catches traces I left unfinished: an accepted AI suggestion without the first-failure mark shows up as "unmarked" rather than as reviewed.

## Remaining limitation: session grouping depends on a local, recovered mapping

Because the traces don't carry `cartwheel.session_id`, the grouping for these traces depends on the local session store (`.sessions.db`, not committed) and on text-and-time matching. The saved map makes the grouping reproducible, but a trace outside the map is shown alone as "unmatched" and isn't merged. New runs will need the server to record the session ID on the trace. My free-form notes are also stored only in the local state files; only accepted present/absent judgments are written to Langfuse as scores.

## Data source

I reviewed the Part A traces in the live Langfuse project on 2026-09-18. On 2026-09-19 the local Langfuse (`localhost:3000`) was unreachable while the interface was being designed, so the trace structure was studied from the Module 1 export (`traces/support_traces.json`), which uses the same trace IDs. The finished interface was then checked against live Langfuse: it loaded 416 traces, hid 66 pilot and manual traces from outside my HW3 final run, and grouped the remaining 350 traces into 250 sessions.
