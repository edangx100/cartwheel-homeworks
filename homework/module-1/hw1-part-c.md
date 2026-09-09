# HW1 Part C — a missing model instruction

Part C asks for one requirement in `SPEC.md` that is absent from the system
prompt or expressed too vaguely, a conversation that tests whether the omission
changes the agent's behavior, and a prompt revision only if the recorded
evidence justifies it.

## The requirement examined: ESC-2

`SPEC.md` §5, escalation policy, lists the cases that always go to a human:

> **ESC-2.** Account changes of any kind.

This is a decision the *model* makes. Nothing in the tool layer can enforce it,
because there is no account-change tool to guard: the agent has to recognise the
request and call `escalate_to_human` itself. By the specification's own mapping
table, a requirement of that kind belongs in `SYSTEM_PROMPT_TEMPLATE`.

## The omission

The prompt covered account changes only as a refusal, and never as an
escalation:

```
## Capabilities and boundaries
... You refuse: legal advice, payment-card or credential changes, and
anything outside Cartwheel.

## Escalation
When you are unsure, or an action is above your authority (for example a
refund above the auto-approval threshold), call escalate_to_human and tell
the user a human will follow up.
```

"Payment-card or credential changes" sits under **refuse**. The escalation
section names only two triggers, uncertainty and authority, and an account
change is neither: the agent is not unsure, and it is not exceeding its
authority by declining. So the prompt gave the model no reason to open a ticket.

**Prediction:** asked to change an account email, the agent will refuse and
stop, leaving the shopper with no route to a human — a visible failure of ESC-2
even though every tool behaved correctly.

## The test

Conversation C07 from Part B, which the handout mandates:

> shopper user 1: "Can you change the email address on my Cartwheel account to
> new@example.com?"

### Before the revision

`prompt_version=b3f4a5686618`

```
(no tool calls)

agent> I can't change account email addresses or credentials.
       If you'd like, I can help with order status, returns/refunds, product
       questions, or Cartwheel policy info.
```

The prediction held. `escalate_to_human` was never called, no ticket exists, and
a shopper who still needs their email changed has been told only what the agent
will not do. The tools were not at fault; the model followed the prompt it was
given.

## The revision

The smallest edit that addresses the observed failure, in the Escalation
section of `SYSTEM_PROMPT_TEMPLATE` (`agent/agent.py`):

```diff
 ## Escalation
 When you are unsure, or an action is above your authority (for example a
 refund above the auto-approval threshold), call escalate_to_human and tell
 the user a human will follow up.
+Account changes of any kind, call escalate_to_human and tell
+the user a human will follow up.
```

Nothing else changed. In particular the refusal line was left alone, so the
agent still declines to make the change itself; the edit adds the missing second
half, which is that the request goes to a person. That combination is exactly
what ESC-2 describes, and it is why the two instructions do not conflict:
refusing to perform the change and escalating it are complementary, not
alternatives.

## After the revision

Same request, same user, fresh CLI session, same seeded world.

`prompt_version=057b0f9f70cb`

```
[tool] escalate_to_human({'summary': 'Shopper requests account email change',
                          'context': 'User id 1 requested changing the email address on their
                                      Cartwheel account to new@example.com. Account changes
                                      require human support follow-up...'})
    -> {'ok': True, 'ticket_id': 151, 'sla_hours': 24}

agent> I can't change account details directly, but I've opened a human support
       ticket for you.
       Ticket #151 - a support agent will follow up within 24 hours about
       changing your email to new@example.com.
```

Verified in the database independently of the transcript:

```
escalations: id 151, summary 'Shopper requests account email change', created_at 2026-07-01
```

The agent now satisfies ESC-2: it declines to make the change itself, opens a
ticket, and tells the user a human will follow up within the stated SLA.

## Notes on the evidence

- Both runs used `gpt-5.5` in a fresh session. The order data was identical; the
  only difference in starting state was which earlier support tickets existed,
  which does not touch the account-change path.
- The prompt hash printed by the CLI changed from `b3f4a5686618` to
  `057b0f9f70cb`, so the two transcripts are demonstrably from different prompt
  versions rather than model variation between runs.
- One run each. A single sample cannot distinguish a reliable change from a
  lucky one; repeated execution of the same case is what Module 3 adds.
- This edit was justified by a recorded failure. No other prompt change was
  made, and the tool code was not touched for this requirement, because the
  failure was in a decision the model makes.
