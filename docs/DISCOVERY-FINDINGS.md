# What was already known about A2A discovery

Carried from the repo this forked from,
[multicloud-a2a-subagent](https://github.com/xbill9/multicloud-a2a-subagent),
whose `docs/INTEROP.md` is the full document. Only the **discovery** findings
are reproduced here. The rest of that file is about invocation, latency and
judging, and copying it across would mean this repo asserting things it has
not itself measured.

Everything below was measured on the deployed three-cloud mesh, not on the
local specimens, and the dates are the original ones.

Two findings this fork has re-measured for itself, on 2026-08-24, are in
`README.md` rather than here: the two card shapes served by ADK and a2a-sdk on
one machine, and where each of them declares `protocolVersion`.

---

## Finding: AgentCore least privilege needs `GetAgentCard`, not `Resource: "*"` (2026-08-12)

The predecessor series left this open: scoping
`bedrock-agentcore:InvokeAgentRuntime` to `runtime/<id>` and `runtime/<id>/*`
was denied 403 **on the agent-card fetch**, and only `Resource: "*"` worked.
Carried into `CLAUDE.md` as unfinished business for whoever deployed against
AgentCore next.

Measured here on a live three-cloud run. This policy works — card fetch and
invocation both 200, no wildcard resource anywhere:

```json
{
  "Action": ["bedrock-agentcore:InvokeAgentRuntime",
             "bedrock-agentcore:GetAgentCard"],
  "Resource": ["arn:aws:bedrock-agentcore:us-west-2:...:runtime/currency_aws-Z3xfNz6IqZ",
               "arn:aws:bedrock-agentcore:us-west-2:...:runtime/currency_aws-Z3xfNz6IqZ/*"]
}
```

So the resource scope was never the problem. **Discovery is a separate action**
— `GetAgentCard` — and a policy granting only `InvokeAgentRuntime` denies the
card fetch however the resources are written. Widening to `Resource: "*"`
appeared to fix it because a wildcard resource with the wrong action set still
fails; what actually differed in the working case was something else in the
policy. The honest limit on this claim: the predecessor's exact failing policy
is in another repo and not in hand, so "the missing element was the action"
is a strong inference from this measurement rather than a diff of the two.

The general shape is one this project keeps meeting: **discovery is privileged
separately from invocation on all three clouds**, and a credential that reaches
the call but not the card produces a failure that surfaces nowhere near auth.
That is why `cards/fetch.py` attaches the credential to the httpx *client*
rather than to a single request, and why `peers/trace.py` files the card
fetch under its own `discovery` phase.


---

## Finding 2: ADK's `to_a2a()` advertises its bind address

`to_a2a(agent, host, port)` writes `host:port` straight into the agent card's
`supportedInterfaces[].url`. On Cloud Run the process binds `0.0.0.0:8080`, so
the deployed card advertises an address no client can route to. The live
Cloud Run agent from the earlier two-cloud work still shows it:

```console
$ curl -s https://currency-adk-a2a-...run.app/.well-known/agent-card.json
{"supportedInterfaces":[{"url":"http://127.0.0.1:8080","protocolBinding":"JSONRPC"}], ...}
```

Clients that route by card URL — including the `a2a-sdk` reference client —
are unreachable against it without rewriting the interfaces after resolution
(the parent repo's `clients/a2a_sdk.py`). The AWS and Azure agents here take a `PUBLIC_URL`
environment variable and advertise that instead, which is the behaviour ADK is
missing rather than anything clever.

This does **not** reproduce on a local mesh, where bind address and dial
address coincide. It needs a deployment, or a deliberate mismatch, which is
why it survived into production in the first place.

### Confirmed on this repo's own deployment (2026-07-31)

The GCP agent is now on Cloud Run, and it reproduces exactly:

```console
$ curl -sH "Authorization: Bearer $(gcloud auth print-identity-token)" \
    https://currency-gcp-...run.app/.well-known/agent-card.json
{"url": null,
 "additionalInterfaces": [{"url": "http://0.0.0.0:8080", "protocolBinding": "JSONRPC", ...}]}
```

A public HTTPS endpoint advertising unroutable plaintext `http://0.0.0.0:8080`.
Hosted it is strictly worse than the two-cloud sighting above: `127.0.0.1` at
least resolves, and the scheme downgrade is new.

**Which clients survive it is the opposite of what finding 3 predicts.** Same
deployed server, one matrix column:

| client | local | deployed |
|---|---|---|
| `a2a-sdk` | ok 69ms | **ok 1027ms** — rewrites the interfaces after resolution |
| `agent-framework` `A2AAgent` | ok 31ms | **ok 424ms** — never routes by card, so the bad card is inert |
| `google-adk` `RemoteA2aAgent` | ok 864ms | **fails** — routes by card, dials `0.0.0.0:8080` |

`agent-framework` cannot *express* the workaround (finding 3) and does not need
it, because it dials the URL it was constructed with. The stack that fails is
**ADK's own client against ADK's own server** — `to_a2a()` writes the bind
address and `RemoteA2aAgent` honours it, so the one pairing that is entirely
one vendor's code is the one that cannot complete a hop. Both halves ship
green in Google's own tests, because locally the two addresses coincide.


---

### AgentCore drops the `A2A-Version` header

**A confirmation rather than a discovery**, since the mechanism was already
known. The predecessor series identified a proxy
silently stripping this header, including the detail that a *missing* header
then reads as an old client; it was written into `docs/ARTICLE_PLAN.md` before
this mesh existed. What is new here is narrower: it reproduced on **AgentCore
specifically**, with two control clouds forwarding the same header untouched,
and it now has a fix. That is a good result and not a first sighting.

The mechanism, for the record. `a2a-sdk` reads the
protocol version from an `A2A-Version` request header and, when it is
**absent**, assumes `0.3` and rejects the request its own handler cannot
serve:

```
Version mismatch: actual='0.3', expected='1.0'
A2A version '0.3' is not supported by this handler. Expected version '1.0'.
```

Cloud Run and Container Apps forward that header untouched. AgentCore does not.
So the same client, the same `a2a-sdk` 1.1.2 on both ends, and the same server
code succeed on two clouds and fail on the third — with an error that blames
the protocol version and names nothing about the platform that removed it.

It had been latent for a week. The deployed AWS image dated from 2026-08-02 and
predated the version check; rebuilding it onto a current `a2a-sdk` is what
exposed a gap that was there all along. **The AWS leg's green cells had been
green for a reason that stopped being true the moment the image was rebuilt.**

`agents/serving.py` now fills the header when it is missing, and only when it
is missing — a header that says `0.3` is a real client statement and is still
rejected. Absent is not evidence of an old client; it is no evidence at all.

