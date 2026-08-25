# Reading Agent Cards Across Three Clouds with A2A, MCP-Free Python and a Laptop

## What is this project trying to Do?

This project is an interoperability instrument for the A2A protocol. It fetches
the agent card from every agent in a mesh, stores the exact bytes each server
sent, and reads them side by side to find out where three cloud runtimes
disagree about what an agent card is.

It never invokes anything. There is no model, no prompt and no token spend in
the measurement path. The whole tool stops at discovery, which turns out to be
where the interesting differences live.

We ran it against two targets on 2026-08-25: three local specimens on
`127.0.0.1`, and the three deployed agents on Cloud Run, Bedrock AgentCore and
Azure Container Apps. Every number in this article comes from those two runs.

## Why discovery is its own problem

Discovery is privileged separately from invocation on all three clouds. On AWS
it is literally a different IAM action — `bedrock-agentcore:GetAgentCard`, not
`bedrock-agentcore:InvokeAgentRuntime`.

That has a consequence worth stating early. A credential can reach the call and
fail on the card, and the failure surfaces as a transport or protocol error
nowhere near auth. This is why the credential here is attached to the httpx
**client** rather than to one request.

The agent card is also the only thing a client reads before it commits to a
runtime. If two vendors describe the same agent differently, every routing
decision downstream inherits that difference.

## The A2A Stack on Each Cloud

The three agents speak the same protocol and almost nothing else is the same.
Here is what actually runs on each leg, and where each one puts the card.

| | GCP | AWS | Azure |
|---|---|---|---|
| host | Cloud Run | Bedrock AgentCore | Container Apps |
| card producer | `google-adk` `to_a2a()` | `a2a-sdk` reference routes | Agent Framework ⚠️ |
| discovery path | `/.well-known/agent-card.json` | `/runtimes/<escaped-arn>/invocations/.well-known/agent-card.json` | `/.well-known/agent-card.json` |
| edge identifier | `server: Google Frontend` | — | `x-ms-middleware-request-id` |
| request id | `x-cloud-trace-context` | UUID | — |
| credential | Google ID token | SigV4 | Entra bearer |
| discovery privilege | `roles/run.invoker` | `bedrock-agentcore:GetAgentCard` | Container Apps auth |

Three details in that table cost real time, so they are worth pulling out.

**AWS serves the card under the invocation path.** GCP and Azure both publish at
the well-known path on their own hostname. AgentCore does not have a per-agent
hostname at all — the runtime is addressed by URL-escaped ARN, and the card sits
*beneath* the same `/invocations/` path the calls use:

```
https://bedrock-agentcore.us-west-2.amazonaws.com
  /runtimes/arn%3Aaws%3Abedrock-agentcore%3A...%3Aruntime%2Fresearch_aws-...
  /invocations/.well-known/agent-card.json
```

That shape broke our own tracer. It classified a round trip as discovery only
when the path *equalled* a known card path or *began* with `/.well-known/`, so
every AgentCore card fetch was filed as an `invoke` — in a tool whose premise is
that it never invokes anything. It is matched on the suffix now.

**Discovery is a separate IAM action on AWS.** `bedrock-agentcore:GetAgentCard`
is not `bedrock-agentcore:InvokeAgentRuntime`. A policy granting only the second
denies the card fetch however the resources are written, and the denial surfaces
as a protocol error nowhere near auth.

**Azure denies before the container.** The 401 carries
`www-authenticate: Bearer realm=...` and `x-ms-middleware-request-id`, and no
`server` header from the app. That is the Container Apps auth middleware —
configured `unauthenticatedClientAction: Return401` — answering on the agent's
behalf. The Agent Framework process never sees the request, which is why we can
describe its card producer but cannot show you its card.

⚠️ Azure's card producer is the one cell in that table we have **not** measured.
It is what the deployment is configured as, carried over from the project this
forked from. Everything else is read off a response we actually received, and
until the card can be fetched we are not going to claim otherwise.

Versions, for the record: `a2a-sdk` 1.1.2, `google-adk` 2.6.3, `httpx` 0.28.1,
`starlette` 1.3.1 on Python 3.13.14. Nothing is pinned.

## Where do I start?

Start with the control, not the clouds. Two SDKs on one machine, serving cards
that no cloud and no model has touched:

```bash
uv pip install --system -e '.[specimens,dev]'   # no virtualenv
./infra/run_mesh.sh start
```

The start script checks that its own process survived, not just that something
answers on the port. That check exists because the first comparison this repo
ever produced was **of the wrong agents** — another project's mesh was already
on those ports, and the health check reached it happily.

```
gcp starting on :11001 (pid 171954)
aws starting on :11002 (pid 171955)
azure starting on :11003 (pid 171956)
waiting for health...
  gcp ready
  aws ready
  azure ready
```

## Setup the Basic Environment

Nothing in this repo is pinned and there is no virtualenv. Install to the system
interpreter and run the suite with `python3 -m pytest`.

```bash
python3 -m pytest -q      # 125 passed
ruff check .              # all checks passed
```

The suite is hermetic. The fetcher's transport is injectable, so it covers the
cases a live cloud will not produce on demand — a card served only on the 0.2
path, a 403 carrying a real AgentCore denial, a 200 carrying an HTML login page.

## Fetch and Review the First Cards

One command dials every peer, reviews each card, contrasts them and stores the
run:

```bash
agentcard fetch --save
```

Here is what came back from the local mesh:

```
run 18cd60a22f1f  3/3 card(s)  56ms

  gcp    200  1.0          675B  none              0 err  0 warn
  aws    200  hybrid       717B  none              0 err  1 warn
  azure  200  hybrid       719B  none              0 err  1 warn
```

Three agents, two card **shapes**. The `gcp` specimen runs Google ADK's
`to_a2a()`; the other two run the `a2a-sdk` reference routes. Nothing about the
agents differs — they all echo text. What differs is the SDK.

## Reading One Card

The reviewer never parses on the way in. A `Specimen` holds the exact body the
server sent, and every later step is a pure function of those bytes plus the
HTTP metadata.

That matters because parsing would throw away the finding. A field a vendor
spells differently, an extra key no client models, a body that is not JSON at
all — all of those survive as evidence only if you keep the bytes.

Findings are split three ways, and the third one is the point:

| severity | meaning | example from this run |
|---|---|---|
| 🔴 error | the card is wrong now | `bind-address-on-card` |
| 🟡 warning | legal but a client will trip | `version-shape-mismatch` |
| 🔵 note | true, not a defect, and the actual product | `version-per-interface` |

Notes are separated from defects so the defects stay findable — not so the notes
can be filtered away.

## Where the Two SDKs Disagree

The contrast block is the compare-and-contrast engine. On the local mesh it
found four client-visible differences:

```
contrast: 4 client-visible difference(s)
  card revision (from its keys):
    gcp    1.0        aws    hybrid     azure  hybrid
  protocolVersion as declared:
    gcp    -          aws    0.3        azure  0.3
  protocolVersion declared per interface:
    gcp    1.0        aws    -          azure  -
  skill ids:
    gcp    card_specimen   aws  echo    azure  echo
```

Look at the two version rows. They reverse exactly.

ADK declares `protocolVersion` **only inside each interface**. The `a2a-sdk`
declares it **only at the top level**, and the value it declares is `0.3` while
the card carries 1.0's `supportedInterfaces`.

The consequence is concrete: a client that branches on `protocolVersion` gets
the wrong answer for both stacks, in opposite directions. Read the top level and
ADK's card looks undeclared. Read the interfaces and `a2a-sdk`'s looks
undeclared. This is why the tool reports the declared version and the inferred
shape as two separate columns.

## Field Presence Across the Mesh

The rows that are not all ticks are exactly where a client needs a fallback:

| top-level key | gcp | aws | azure | what a client loses |
|---|---|---|---|---|
| capabilities | 🟢 | 🟢 | 🟢 | — |
| description | 🟢 | 🟢 | 🟢 | — |
| skills | 🟢 | 🟢 | 🟢 | — |
| supportedInterfaces | 🟢 | 🟢 | 🟢 | — |
| version | 🟢 | 🟢 | 🟢 | — |
| documentationUrl | 🔴 | 🟢 | 🟢 | nowhere to send a human |
| preferredTransport | 🔴 | 🟢 | 🟢 | must pick a binding itself |
| protocolVersion | 🔴 | 🟢 | 🟢 | must infer the revision |
| url | 🔴 | 🟢 | 🟢 | must read `supportedInterfaces` |

## Reaching the Deployed Three

The deployed agents answer 401 or 403 to anyone without a federated credential.
That is the deployment, and it is the point.

The parent project reaches them from a coordinator running on Cloud Run, which
can mint workload OIDC tokens for an arbitrary audience. All three legs start
from a token minted at the GCE metadata server — and a workstation has none.

| leg | federated mechanism |
|---|---|
| → GCP | Google ID token, `roles/run.invoker` |
| → AWS | metadata mint → STS `AssumeRoleWithWebIdentity` → SigV4 |
| → Azure | Entra Federated Identity Credential on `accounts.google.com` |

That gap read as absolute. It is not.

## What a Workstation Can Actually Reach

Only the *federated* path needs a metadata server. Two of the three clouds
accept a credential a laptop already has, so we added two modes for it.

First check what the CLI will mint:

```bash
gcloud auth print-identity-token --audiences=https://research-gcp-...run.app
```

Here is what we found:

```
ERROR: (gcloud.auth.print-identity-token) Invalid account type for
`--audiences`. Requires valid service account.
```

A user account cannot pin the audience. So the token that comes back carries
`aud` = gcloud's own OAuth client id, `32555940559.apps.googleusercontent.com`,
and **not** the Cloud Run service URL that the code was written to satisfy.

Cloud Run accepts it anyway, honouring Google's allowlisted CLI client id. The
card arrives, and the audience condition the code appears to be exercising was
never checked. The mode logs a warning naming this every time it falls back,
because a green row here is evidence of IAM role membership and nothing more.

| workstation mode | what it proves | what it does not |
|---|---|---|
| `gcloud-id-token` | the developer holds `roles/run.invoker` | nothing about the coordinator's service account |
| `aws-sigv4-local` | that identity holds `GetAgentCard` | nothing about the role trust policy |

`aws-sigv4-local` reuses the same SigV4 signer as the federated mode and swaps
only the origin of the key. It is deliberately **not** counted as keyless: it
mints nothing, so it looks keyless, but what it reads off the disk is very often
a static access key and it cannot tell which it got.

## We Have Cards!

Point the tool at a peers file and fetch the real thing:

```bash
agentcard --corpus-dir .cards-deployed fetch --peers-file peers.toml --save
```

```
run 07f23fc6df3f  2/3 card(s)  25594ms

  gcp    200  1.0          528B  gcloud-id-token   1 err  2 warn
  aws    200  hybrid      2109B  aws-sigv4-local   0 err  2 warn
  azure  FAILED  authentication: 401 on /.well-known/agent-card.json
```

Two of three, from a laptop, against two clouds. The Azure leg stays in the
corpus as a row rather than a gap — a blank column reads as "this peer disagrees
with everyone", which is the opposite of what a denial means.

## Cross Check the Deployed Cards

The most important result is the boring one. **Both card shapes from the local
mesh reproduce exactly on the deployed pair**, so they were never an artefact of
the specimen code.

| peer | runtime | shape | `protocolVersion` top level | per interface |
|---|---|---|---|---|
| gcp | Cloud Run / ADK `to_a2a` | 1.0 | absent | `1.0` |
| aws | Bedrock AgentCore / a2a-sdk | hybrid | `0.3` | absent |

A client branching on that field still gets the wrong answer for both stacks
against real deployments.

## What Each Runtime Puts on a Card

This is the sharpest contrast in the run, and no conformance checker would flag
either side. Same logical agent — it writes a short, sourced research brief —
described twice.

ADK publishes the agent's own description as one skill:

```json
"skills": [{ "id": "research_agent", "name": "custom",
             "tags": ["custom_agent"] }]
```

AgentCore publishes the agent's **entire system prompt** as the skill
description — 1,258 characters of instruction text — and names the model
in the tags:

```json
"skills": [{ "id": "research_brief", "name": "research brief",
             "description": "You are a research assistant with a web_search
                             tool. Given a topic, you write one short research
                             brief and nothing else...",
             "tags": ["research","writing","analysis","brain:llm",
                      "model:us.amazon.nova-micro-v1:0"] }]
```

Sit with that. The card is the document you hand anyone who can reach discovery,
and on this runtime it carries the prompt and the model id.

Neither card declares a `securitySchemes` block, though both demand a
credential. A client that discovers either agent learns nothing from the card
about why its next request will be rejected.

## The Defects

Six findings on the deployed run, and only one of them is a vendor bug:

| sev | peer | code | detail |
|---|---|---|---|
| 🔴 | azure | `no-card` | 401; the tenant's Entra app has not consented to the CLI client id |
| 🔴 | gcp | `bind-address-on-card` | advertises `http://0.0.0.0:8080` |
| 🟡 | gcp | `plaintext-url` | `http://` for a remote agent |
| 🟡 | gcp | `undeclared-auth` | fetched with a credential, names no `securitySchemes` |
| 🟡 | aws | `undeclared-auth` | same, on the other cloud |
| 🟡 | aws | `version-shape-mismatch` | declares `0.3`, shaped like hybrid |

ADK's `to_a2a()` writes its bind address straight onto the card. On Cloud Run
the process binds `0.0.0.0:8080`, so a public HTTPS endpoint advertises
unroutable plaintext to every client that routes by card URL.

It does not reproduce on a local mesh, where the bind address and the dial
address coincide. That is how it survived into production, and it was still
there on 2026-08-25.

## Catching a Card That Moved

Now the result we did not plan. Five runs of the same peer, same endpoint, same
credential, across three and a half hours:

| run | time (UTC) | `version` | skills | bytes |
|---|---|---|---|---|
| `8c201b95f349` | 14:10:24 | `0.0.1` | 4 | 1533 |
| `2a4992c4372b` | 15:58:28 | `0.0.1` | 4 | 1533 |
| `05bb15448c63` | 16:01:04 | `0.0.1` | 4 | 1533 |
| `07f23fc6df3f` | 17:17:39 | `0.0.1` | **1** | **528** |
| `6dedd20d0b05` | 17:40:46 | `0.0.1` | **1** | **528** |

This is a clean step change, not a flake. Three runs sit on one side of it and
two on the other, byte-for-byte stable within each group. The card lost two
thirds of its bytes and three of its four skills, and `version` never moved.

```
05bb15448c63 → ['research_agent',
                'research_agent-sub-agents',
                'research_agent_gemini_research_agent_gemini',
                'research_agent_gemini_research_agent_gemini-web_search']

07f23fc6df3f → ['research_agent']
```

What went was the flattened composition — the sub-agent list, the sub-agent's
model, and its `web_search` tool. A router that had discovered this agent an
hour earlier and cached "it can search the web" was, by the second run, holding
a claim the card no longer makes.

**The review output is identical across the change.** We diffed the two defect
blocks directly; they match line for line:

```bash
diff <(agentcard replay 05bb15448c63) <(agentcard replay 07f23fc6df3f)   # defects block: no output
```

Same `1 err 2 warn` on this peer, the same six defects run-wide, the same codes
at the same severities. Not one finding moved — the error is the pre-existing
`bind-address-on-card`, true of both cards and silent about what changed between
them.

A checker that asks only *is this card conformant* therefore reports no
difference, because on that question there is none. The card that lost three
skills is exactly as conformant as the one that had them. This is the whole
argument for storing the bytes and dating the corpus.

## Gating a Build on Drift

Validity and change are opposite kinds of news, so they get different exits.

```bash
agentcard fetch --save --fail-on-change     # exit 4 if any card moved
agentcard fetch --fail-on-defect            # exit 2 if any card is wrong
```

We measured that neither substitutes for the other. Restart a specimen
advertising a different URL and `--fail-on-defect` exits `0` while
`--fail-on-change` exits `4` and names the field.

| exit | meaning |
|---|---|
| 0 | ran, nothing gated |
| 1 | bad invocation |
| 2 | `--fail-on-defect` — a card is wrong now |
| 3 | no peer served a card at all |
| 4 | `--fail-on-change` — a card differs from the previous run |

Exit 3 is separate on purpose. A harness has to distinguish *the instrument
failed* from *the instrument worked and the news is bad*.

One rule keeps the comparison honest: **a peer name is not an identity**. The
local specimens and the deployed agents are both called `gcp`, `aws` and
`azure`, so a corpus holding both would diff a laptop specimen against Cloud Run
and call it vendor drift. A peer whose endpoint moved now prints as
`[not compared]` and never trips the gate.

## Discovery Cost Breakdown

Not on any card, and worth knowing. A card fetched over a federated credential
costs round trips to another cloud's identity provider first, and arrives
byte-identical to one fetched from an open port.

| peer | auth | keyless | round trips | discovery ms |
|---|---|---|---|---|
| gcp (local) | none | 🟢 yes | 1 | 16 |
| aws (local) | none | 🟢 yes | 1 | 9 |
| azure (local) | none | 🟢 yes | 1 | 6 |
| gcp (deployed) | `gcloud-id-token` | 🟢 yes | 1 | 175 |
| aws (deployed) | `aws-sigv4-local` | 🔴 no | 1 | 695 |
| azure (deployed) | none | 🟢 yes | 1 | 25 550 |

⚡ The whole local mesh answers in **56 ms**. The deployed run takes **25.6
seconds**, and 25.5 of those are the Azure Container App cold-starting only to
return 401.

💾 Card sizes vary by 4× across runtimes serving the same agent: 528 bytes from
ADK on Cloud Run, 2 109 bytes from AgentCore.

## Comparison with Other Approaches

| approach | catches invalid cards | catches vendor drift | needs the agent running | cost |
|---|---|---|---|---|
| read the spec | 🔴 no | 🔴 no | no | free |
| a JSON-schema validator | 🟢 yes | 🔴 no | no | free |
| invoke the agent and see | 🟡 partly | 🔴 no | yes | model spend |
| this harness | 🟢 yes | 🟢 yes | yes, discovery only | zero spend |

The row that matters is the drift column. Every other approach reports "no
change" on the card that lost three skills.

## Validating the Claims

A tool that reports a finding is not evidence that the finding is true — the
report and the bug would come from the same code. So every claim above was
re-checked, and wherever possible re-checked with `curl` and `python -c`,
with none of this project in the path.

| claim | how it was checked | result |
|---|---|---|
| Two SDKs, two card shapes | `curl` both local cards | 🟢 holds |
| `protocolVersion` in opposite places | `curl`, read the field directly | 🟢 holds |
| Both shapes reproduce when deployed | parsed the servers' stored raw bytes | 🟢 holds |
| Live card advertises `0.0.0.0:8080` | `curl` the deployed Cloud Run card | 🟢 holds |
| Neither deployed card declares auth | `curl` / raw bytes | 🟢 holds |
| The runtimes disagree on "skill" | raw bytes, field by field | 🟢 holds |
| A card changed with no version bump | five stored runs over 3.5 h | 🟢 holds |
| The review did not notice | `diff` of both review outputs | 🟢 identical |
| The two gates catch different things | both run on the same changed card | 🟢 0 vs 4 |
| `replay` never dials | killed every server, then replayed | 🟢 holds |
| A peer name is not an identity | diffed a local run against a deployed run | 🟢 not gated |

The independence matters most for the version claim. Here is that check with no
tooling at all:

```console
$ curl -s http://127.0.0.1:11001/.well-known/agent-card.json | python3 -c "..."
  top-level protocolVersion : None
  per-interface            : ['1.0']

$ curl -s http://127.0.0.1:11002/.well-known/agent-card.json | python3 -c "..."
  top-level protocolVersion : '0.3'
  per-interface            : [None]
```

The `replay` check is the other one worth showing, because it is a claim about
what the tool does *not* do. Stop every server, confirm nothing is listening,
then replay a run that fetched three cards:

```console
$ ss -ltn | grep -c '1100[123]'
0
$ agentcard replay
run 1657b2be9bff  3/3 card(s)  46ms
  gcp    200  1.0          675B  none              0 err  0 warn
  aws    200  hybrid       717B  none              0 err  1 warn
  azure  200  hybrid       719B  none              0 err  1 warn
```

Three cards reviewed with every server dead. It cannot have dialled.

Two apparent failures during this pass turned out to be faults in the *test*,
not the tool, and both are worth naming because they are easy to repeat.
`--fail-on-defect` looked like it exited `2` instead of `0` — we had re-fetched
before the restarted specimen was serving, so the run recorded a real `no-card`
error. And `replay` printed nothing once, because the run we asked for had been
fetched without `--save` and was never stored; the tool said exactly that and
exited `1`.

One claim did not survive the pass. An earlier draft said both sides of the
drifted card *passed every check*. They do not — the pre-existing
`bind-address-on-card` error is present before and after. Stated correctly the
finding is sharper: the review is not clean on either side, it is **identical**
on both.

## Summary

The strategy for reading A2A agent cards across three clouds was validated with
an incremental, control-first approach.

- 🟢 **The local mesh is the control.** Two SDKs on one machine produced two
  card shapes with no cloud involved, so anything that differs, differs because
  of the SDK.
- 🟢 **Both shapes reproduce on real deployments**, measured 2026-08-25. A
  client branching on `protocolVersion` gets the wrong answer for both stacks,
  in opposite directions.
- 🟢 **Two of three clouds are reachable from a workstation**, using credentials
  a laptop already has — and the report names the mode on every row, because
  those modes prove strictly less than the federated path they stand in for.
- 🟢 **The runtimes disagree about what a skill is.** ADK flattens its
  composition tree onto the card; AgentCore publishes the system prompt and the
  model id.
- 🟢 **A live card changed with no version bump.** Five runs over three and a
  half hours show a clean step change from four skills to one, and the review
  output is *identical* on both sides of it — not clean, identical. A checker
  that asks only "is this card conformant" reports no difference, because on
  that question there is none.
- 🟢 **The three stacks agree on the protocol and little else.** AWS serves the
  card beneath the same `/invocations/` path the calls use; GCP and Azure
  publish at the well-known path on their own hostname. Discovery is a separate
  IAM action on AWS, and on Azure the denial comes from platform middleware
  before the container is ever reached.
- 🔴 **Azure remains shut.** Its Entra app has not consented to the CLI client
  id, so opening it needs an admin consent grant or a client secret.

Every claim above was re-checked with `curl` and `python -c`, with none of this
project in the path, because a tool reporting its own finding is not evidence
that the finding is true. One claim did not survive that pass and was corrected
rather than quietly dropped.

The instrument stores the bytes and dates every corpus, which is what makes the
drift finding visible at all. Cards change without notice and without a version
bump — so every claim in this article names the date it was measured on.

The code is at
[xbill9/multicloud-agentcard](https://github.com/xbill9/multicloud-agentcard).
