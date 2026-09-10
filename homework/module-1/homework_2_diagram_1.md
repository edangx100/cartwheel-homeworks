# Homework 2 — Diagram 1: from your message to the trace

How one request travels from an HTTP client, through the endpoint, into the
agent and its tools, and out to Langfuse as a trace.

Two things happen, in order: you **create a session** once, then you **send
messages** to it. The first establishes who you are; the second is where the
work and the tracing happen.

```mermaid
flowchart TD
    You["You<br/>curl or any HTTP client"]

    subgraph B["Part B &nbsp;·&nbsp; POST /sessions"]
        direction TB
        CS["create_session<br/><i>server/app.py</i>"]
        DB[("data/cartwheel.db<br/>users table")]
        RoleOK{"stored role ==<br/>claimed role?"}
        E400["HTTP 400<br/>unknown role"]
        E404["HTTP 404<br/>unknown user id"]
        E403["HTTP 403<br/>role mismatch"]
        Ctx["AuthContext<br/>user_id, role, store_id<br/><b>built from the database</b>"]
        Save["_SESSIONS session_id =<br/>AuthContext + SQLiteSession"]
        Sign["sign token<br/>body + HMAC signature"]
    end

    subgraph C["Part C &nbsp;·&nbsp; POST /sessions/id/messages"]
        direction TB
        PM["post_message<br/><i>server/app.py</i>"]
        Authz["_authorize<br/><i>provided</i><br/>401 missing or bad token<br/>403 token for another session<br/>404 unknown session"]
        Recover["recover AuthContext<br/>from _SESSIONS<br/><b>never from the message text</b>"]
        Root["open ROOT span<br/><b>cartwheel.session_message</b><br/>user_role · user_id<br/>prompt_version · scenario_id<br/>gen_ai.input.messages<br/>gen_ai.output.messages"]
        Run["Runner.run agent, message, context"]
        Model["model span<br/>gen_ai.request.model<br/>gen_ai.usage.*"]
        TSpan["tool span<br/>gen_ai.operation.name = execute_tool<br/>gen_ai.tool.name"]
        Tool["tool body<br/><i>agent/tools.py</i>"]
        Matrix["access matrix check<br/><i>agent/auth.py</i>"]
        Rec["record_tool_result<br/><i>observability/instrument.py</i><br/>adds cartwheel.user_role<br/>cartwheel.user_id · store_id<br/>cartwheel.permission_denied<br/>+ .reason when denied"]
        Reply["final assistant reply"]
    end

    LF[/"Langfuse<br/>http://localhost:3000"/]

    You -->|"1 . user_id + role"| CS
    CS --> RoleOK
    CS -.->|"role not in ROLES"| E400
    CS -->|"look up the user"| DB
    DB -.->|"no such user"| E404
    RoleOK -->|"yes"| Ctx
    RoleOK -.->|"no"| E403
    Ctx --> Save --> Sign
    Sign -->|"2 . session_id + token"| You

    You -->|"3 . message + Bearer token"| PM
    PM --> Authz --> Recover --> Root --> Run
    Run --> Model
    Run --> TSpan --> Tool --> Matrix --> Rec
    Rec --> Reply
    Reply -->|"4 . session_id, reply, prompt_version"| You

    Root -.->|"spans exported over OpenTelemetry"| LF
    Model -.-> LF
    TSpan -.-> LF

    classDef yours stroke:#c0392b,stroke-width:3px
    classDef auto stroke:#7f8c8d,stroke-width:1px,stroke-dasharray: 5 3
    classDef err stroke:#c0392b,stroke-width:1px,stroke-dasharray: 2 2
    class CS,Ctx,Save,Sign,PM,Recover,Root,Rec yours
    class Model,TSpan,Authz auto
    class E400,E403,E404 err
```

**Legend.** Thick red outline = code you write in Homework 2. Dashed grey =
provided or recorded automatically by OpenLLMetry. Dotted red = error paths the
handout requires.

## Reading the diagram

| Stage | What happens | Why it matters |
|---|---|---|
| 1 | You claim a user id and a role | A *claim*, nothing more — not yet trusted |
| — | `create_session` reads the users table | The database is the authority, not the request |
| — | Claimed role vs stored role | Mismatch is HTTP 403. This is the check that stops "I am support staff" |
| 2 | Server returns a session id and a signed token | Identity is now stored **server-side** |
| 3 | Each message carries the token | Proves entitlement to that session |
| — | Root span opens | Everything below it shares one `trace_id` |
| — | Tools run and check the matrix | `agent/auth.py` enforces it in code, not in the prompt |
| — | `record_tool_result` fires | Your `cartwheel.*` attributes land on the tool span |
| 4 | Reply returns, spans export | The trace becomes the durable record |

Note that `record_tool_result` runs **inside** the tool span, not after it.
`_call` in `agent/agent.py` invokes it while that span is still active, which is
why `trace.get_current_span()` finds the right span to write to.

---

# What the token is

"Token" means two unrelated things in this assignment, and both appear in your
traces:

| "token" | Meaning | Where you see it |
|---|---|---|
| **auth token** | a pass that proves who you are | `Authorization: Bearer …` |
| **model token** | a chunk of text the model reads or writes | `gen_ai.usage.input_tokens` |

Everything below is the first one.

## A coat-check ticket

You hand over your identity **once**, at the cloakroom (`POST /sessions`). The
server checks it against the database, stores your coat, and gives you a ticket.
Every later time you come to the counter you don't re-explain who you are — you
show the ticket.

Without it you would have to resend `user_id` and `role` with every message, and
the server would have to simply believe you. Anyone could claim the support role
and read every order in the system.

## What is actually inside it

Not magic — two pieces of text joined by a dot. The real code, from
`server/app.py`:

```python
def create_token(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True).encode()
    ).decode()
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"
```

So a token looks like this:

```
eyJpc3N1ZWRfYXQiOjE3NTc1…fQ==.4a7d1ed414474e4033ac29ccb8653d9b
└──────────── body ────────────┘└──────── signature ──────────┘
     the facts, base64-encoded     proof they were not edited
```

**The body** is JSON rewritten using only URL-safe characters — that is all
base64 is. Decoded, it holds the five fields the handout requires:

```json
{"issued_at": 1757500000, "role": "shopper",
 "session_id": "3f2a...", "store_id": null, "user_id": 1}
```

**The signature** is the half that does the work. The server holds a private
secret (`CARTWHEEL_DEV_SECRET`). It runs secret + body through a one-way
function to get that fingerprint. When the token comes back, `verify_token`
recomputes the fingerprint and compares:

```python
expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
if not hmac.compare_digest(sig, expected):
    return None
```

Change one character of the body — `"role": "shopper"` to `"role": "support"` —
and the fingerprint no longer matches, so the token is rejected. You cannot
compute a new matching fingerprint without the secret.

Two properties worth remembering:

- **It is not encrypted.** Anyone holding the token can read the body. It is
  tamper-*evident*, not secret. Acceptable here because this is dev-only auth,
  as `server/app.py` says in its own docstring.
- **"Bearer"** means "whoever bears this." No extra password; possession is the
  claim. That is why real systems require HTTPS and expire their tokens.

## The part that matters most

Look at what `_authorize` actually returns:

```python
return _SESSIONS[session_id][0]
```

Not the token's contents — the `AuthContext` from the server's own dictionary.
The token's only job is to prove *which session* you may use. The identity
itself never left the server.

```mermaid
sequenceDiagram
    autonumber
    participant U as You
    participant S as server/app.py
    participant D as cartwheel.db
    participant T as Tools

    U->>S: POST /sessions — I am user 1, a shopper
    S->>D: look up user 1
    D-->>S: stored role = shopper, store_id = null
    Note over S: claim matches the database
    S->>S: AuthContext built from the DATABASE row
    S->>S: _SESSIONS session_id = that context
    S-->>U: session_id + signed token

    U->>S: POST /messages — Bearer token
    S->>S: recompute HMAC, compare signatures
    Note over S: token proves WHICH SESSION,<br/>not who you are
    S->>S: AuthContext looked up in _SESSIONS
    S->>T: run the agent with that context
    T->>T: agent/auth.py checks the access matrix
    T-->>S: structured tool result
    S-->>U: session_id, reply, prompt_version
```

Same principle as the access matrix, one layer deeper: even the token is not
trusted to say who you are. It says only that you are entitled to a session the
server already decided the identity for.
