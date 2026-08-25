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



---

# Measured by this repo on the deployed three

Everything below was fetched by `agentcard fetch --peers-file peers.toml` from
a **workstation**, on **2026-08-25**, run `8c201b95f349` (stored in
`.cards-deployed/`, not the default local corpus). Full report:
`docs/deployed-2026-08-25.md`. Two of three peers answered; Azure is a denial
row. Per `CLAUDE.md`, every claim here names the date it was true, because
cards change without notice and without a version bump.

The credential matters to how far these claims reach. GCP was fetched with a
developer `gcloud` identity token and AWS with the workstation's own AWS
credentials — **not** the federated workload path the deployed coordinator
uses. What was measured is the *card*; what was not measured is the trust
policy.

## Finding: the two card shapes reproduce on the deployed pair (2026-08-25)

The fork's own first-hour finding — ADK serving a 1.0-shaped card and `a2a-sdk`
a hybrid one — was measured on local specimens, where it could have been an
artefact of the specimen code. It is not. On the deployed agents:

| peer | runtime | shape | `protocolVersion` at top level | per interface |
|---|---|---|---|---|
| gcp | Cloud Run / ADK `to_a2a` | `1.0` | absent | `1.0` |
| aws | Bedrock AgentCore / a2a-sdk | `hybrid` | `0.3` | absent |

So a client branching on `protocolVersion` still gets the wrong answer for both
stacks against real deployments, in opposite directions. AgentCore's card also
earns `version-shape-mismatch`: it declares `0.3` while carrying 1.0's
`supportedInterfaces`.

## Finding: ADK still advertises `0.0.0.0:8080` on a live Cloud Run card (2026-08-25)

Finding 2 above was last confirmed on this repo's deployment on 2026-07-31.
Re-measured today against `research-gcp`, unchanged:

```
ERR  gcp  bind-address-on-card: supportedInterfaces[0] advertises a loopback
          address: http://0.0.0.0:8080
WARN gcp  plaintext-url: supportedInterfaces[0] advertises http:// for a
          remote agent: http://0.0.0.0:8080
```

A public HTTPS endpoint whose card routes clients to unroutable plaintext. It
is the only error-severity defect on either card that is the *vendor's*, and
the harness now catches it without anyone looking.

## Finding: neither deployed card declares the auth it demands (2026-08-25)

Both peers 401/403 without a credential, and both serve a card with no
`securitySchemes`:

```
WARN gcp  undeclared-auth: card was fetched with gcloud-id-token and names no securitySchemes
WARN aws  undeclared-auth: card was fetched with aws-sigv4-local and names no securitySchemes
```

The card is the thing a client reads to learn how to authenticate, and on both
clouds it is silent about it. A client that discovers either agent learns
nothing from the card about why its next request will be rejected. Neither card
is signed, and neither declares `provider`, `documentationUrl` or `iconUrl` —
notes, not defects, and the answer to "what do these runtimes have in common".

## Finding: the two runtimes disagree about what a "skill" is (2026-08-25)

The sharpest client-visible contrast in the run, and it is a `note`-level
difference that no conformance check would flag:

| peer | skill ids |
|---|---|
| gcp | `research_agent`, `research_agent-sub-agents`, `research_agent_gemini_research_agent_gemini`, `research_agent_gemini_research_agent_gemini-web_search` |
| aws | `research_brief` |

The same logical agent. ADK's `to_a2a()` **flattens its internal composition
onto the card** — the agent, its sub-agent list, the sub-agent's model, and the
sub-agent's tools each become a skill, with the tool's Python docstring as the
description. AgentCore publishes one skill, the thing the agent does. A router
choosing between these two by skill count or skill name is comparing an
implementation tree with a capability.

## Finding: a workstation can reach two of the three, and the GCP one is not what it looks like (2026-08-25)

The README's standing gap said a workstation has no metadata server and so
cannot reach any leg. True of the *federated* path, and it hid that two clouds
accept a credential a laptop already has. Both now exist as modes, and both are
labelled on every report row.

The GCP one carries a trap worth stating on its own:

- `gcloud auth print-identity-token --audiences=<service-url>` is **refused for
  a user account** — *"Invalid account type for `--audiences`. Requires valid
  service account."*
- So the minted token's `aud` is gcloud's OAuth client id
  `32555940559.apps.googleusercontent.com`, not the Cloud Run service URL that
  `GoogleIdTokenAuth` was written to satisfy.
- **Cloud Run accepts it regardless**, honouring Google's allowlisted CLI
  client id.

The card therefore arrives, and the audience condition the code appears to be
exercising was never checked. `peers/auth.py` logs a warning naming this every
time it falls back, because a green row here is not evidence about audiences.

## Finding: Azure's card is behind a consent grant, not a credential (2026-08-25)

`research-azure` on Container Apps is configured
`unauthenticatedClientAction: Return401` against app registration
`be143e2d-…` in its own tenant, whose `allowedAudiences` is that same client
id. Requesting a token for it from the
workstation fails before any card fetch:

```
AADSTS65001: The user or administrator has not consented to use the
application with ID '04b07795-8ddb-461a-bbee-02f9e1bf7b46' named
'Microsoft Azure CLI'.
```

This is not a missing credential — the workstation is signed in to the right
tenant. It is that the Azure CLI's own app has no consent to request that
audience. Opening it needs an admin consent grant, or a client secret on the
app registration, which is the one mode in this repo that is not keyless.

It stays in the corpus as a `FAILED` row and is excluded from the contrast
tables, per the ground rule: a blank column would read as "this peer disagrees
with everyone", which is the opposite of what a denial means.

## Finding: a deployed card changed materially, with no version bump, inside one hour (2026-08-25)

The claim in `CLAUDE.md` — *cards change without notice and without a version
bump* — measured on a live deployment rather than asserted. Two runs of the
same peer, same endpoint, same credential, 76 minutes apart:

| run | time (UTC) | `version` | `protocolVersion` | skills | bytes |
|---|---|---|---|---|---|
| `05bb15448c63` | 16:01:04 | `0.0.1` | absent | 4 | 1533 |
| `07f23fc6df3f` | 17:17:39 | `0.0.1` | absent | 1 | 528 |

The card lost two thirds of its bytes and three of its four skills. `version`
did not move. Nothing a client polls could have told it apart from a cache hit.

What went is the flattened composition — `research_agent-sub-agents`,
`research_agent_gemini_research_agent_gemini` and the `-web_search` tool entry
— leaving only `research_agent`. A router that had discovered this agent an
hour earlier and cached "it can search the web" was, by the second run, holding
a claim the card no longer makes.

This is the whole argument for storing the bytes and dating the corpus. The
conformance review is **green on both** cards: nothing here is a defect, both
are legal, and a checker that only asks "is this card valid" reports no change
whatsoever. `agentcard --corpus-dir .cards-deployed diff` reports it in one
line, and `--fail-on-change` exits 4.
