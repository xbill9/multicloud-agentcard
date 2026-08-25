# Cross Cloud A2A Agent Card Field Comparison

![Three agent cards compared side by side. The Cloud Run card on the left is sparse, the AgentCore card in the centre is four times denser, and the Container Apps card on the right is dimmed behind a lock because it returns 401.](article-header.jpg)

Comparing Agent Cards with A2A - This tutorial aims to fetch the agent card from
A2A agents running on several mainstream Cloud providers and compare the fields
they publish.

Same Protocol - Different Cards!

Why do I care what is in the Agent Card? Can't I just call the Agent?

What do the field differences actually mean for a client?

## What is this Approach actually Comparing?

This project fetches the agent card from every agent in a mesh, stores the exact
bytes each server sent, and compares the fields side by side.

It never invokes anything. There is no model, no prompt and no token spend in
the measurement path. It stops at discovery.

The targets are three local specimens on 127.0.0.1 and three deployed agents on
Cloud Run, Bedrock AgentCore and Azure Container Apps. All results below were
measured on 2026-08-25.

## What is an A2A Agent Card?

The agent card is a JSON document published at a well known path. It names the
agent, lists its skills, and declares how to reach it.

It is the only thing a client reads before committing to a runtime. If two
vendors describe the same agent differently, every routing decision downstream
inherits that difference.

The spec places the card at `/.well-known/agent-card.json`, with
`/.well-known/agent.json` as the older path.

## Why is Discovery Privileged Separately from Invocation?

Discovery is a separate permission from invocation on all three clouds. On AWS
it is a different IAM action entirely: `bedrock-agentcore:GetAgentCard`, not
`bedrock-agentcore:InvokeAgentRuntime`.

A credential can reach the call and still fail on the card. The failure surfaces
as a transport or protocol error, nowhere near auth.

This is why the credential is attached to the httpx client rather than to a
single request.

## Tool Chain Setup

Verify that the prerequisite packages are installed - and clone the sample
Github repo:

```console
$ git clone https://github.com/xbill9/multicloud-agentcard
$ cd multicloud-agentcard
$ uv pip install --system -e '.[specimens,dev]'
```

There is no virtualenv and nothing is pinned. The versions in use are a2a-sdk
1.1.2, google-adk 2.6.3, httpx 0.28.1 and starlette 1.3.1, on Python 3.13.14.

## Checking the Developer Environment

Once you have all the tools in place - you can test the installation:

```console
$ python3 -m pytest -q
125 passed in 0.52s

$ ruff check .
All checks passed!
```

The suite is hermetic. The fetcher transport is injectable, so it covers cases a
live cloud will not produce on demand: a card served only on the older path, a
403 carrying a real AgentCore denial, and a 200 carrying an HTML login page.

## Starting the Local Card Specimens

Start with the local control, not the clouds. Two SDKs run on one machine and
serve cards that no cloud and no model has touched:

```console
$ ./infra/run_mesh.sh start
gcp starting on :11001 (pid 171954)
aws starting on :11002 (pid 171955)
azure starting on :11003 (pid 171956)
waiting for health...
  gcp ready
  aws ready
  azure ready
```

The start script verifies that its own process survived, not merely that
something answers on the port. A health check alone reports that some server
answered, and sharing a port range with another project produces three ready
agents and a comparison of the wrong ones.

## A2A Agent Card (Cloud Run / google-adk)

The GCP agent runs on Cloud Run behind IAM. Fetch the card with an identity
token:

```console
$ TOK=$(gcloud auth print-identity-token)
$ curl -s -D - -H "Authorization: Bearer $TOK" \
    https://research-gcp-...run.app/.well-known/agent-card.json
HTTP/2 200
content-type: application/json
x-cloud-trace-context: b398ae03c356ad8b7addc408937df911;o=1
server: Google Frontend
```

The card is served at the well known path on the service hostname. Discovery is
gated by `roles/run.invoker` at the Google Frontend.

The card itself is 528 bytes:

```json
{
  "capabilities": { "pushNotifications": false, "streaming": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "description": "An agent that writes a short, sourced research brief",
  "name": "research_agent",
  "skills": [{ "description": "An agent that writes a short, sourced...",
               "id": "research_agent", "name": "custom",
               "tags": ["custom_agent"] }],
  "supportedInterfaces": [{ "protocolBinding": "JSONRPC",
                            "protocolVersion": "1.0",
                            "url": "http://0.0.0.0:8080" }],
  "version": "0.0.1"
}
```

`to_a2a()` writes the bind address onto the card. On Cloud Run the process binds
`0.0.0.0:8080`, so a public HTTPS endpoint advertises unroutable plaintext to
every client that routes by card URL. This does not reproduce on a local mesh,
where the bind address and the dial address are the same.

## A2A Agent Card (Bedrock AgentCore / a2a-sdk)

AgentCore has no per-agent hostname. The runtime is addressed by URL escaped
ARN, and the card sits beneath the same `/invocations/` path the calls use:

```
https://bedrock-agentcore.us-west-2.amazonaws.com
  /runtimes/arn%3Aaws%3Abedrock-agentcore%3A...%3Aruntime%2Fresearch_aws-...
  /invocations/.well-known/agent-card.json
```

List the runtime and confirm it is ready:

```console
$ aws bedrock-agentcore-control list-agent-runtimes --region us-west-2
[ { "name": "research_aws",
    "arn": "arn:aws:bedrock-agentcore:us-west-2:...:runtime/research_aws-...",
    "status": "READY" } ]
```

The card is 2,109 bytes, four times the size of the Cloud Run card for the same
agent:

```json
{
  "capabilities": { "streaming": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "description": "An agent that writes a short, sourced research brief",
  "name": "research_agent",
  "preferredTransport": "JSONRPC",
  "protocolVersion": "0.3",
  "skills": [{ "description": "You are a research assistant with a
                               web_search tool...",
               "id": "research_brief", "name": "research brief",
               "tags": ["research","writing","analysis","brain:llm",
                        "model:us.amazon.nova-micro-v1:0"] }],
  "supportedInterfaces": [{ "protocolBinding": "JSONRPC",
                            "url": "https://bedrock-agentcore..." }],
  "url": "https://bedrock-agentcore...",
  "version": "0.1.0"
}
```

The path shape has a consequence for any tracer. A round trip classified as
discovery only when the path equals a known card path, or begins with
`/.well-known/`, files every AgentCore card fetch as an invocation. The rule
must match on the suffix.

## A2A Agent Card (Container Apps / Agent Framework)

The Azure agent runs on Container Apps. Fetching the card without a credential
returns a 401:

```console
$ curl -s -D - https://research-azure....azurecontainerapps.io/.well-known/agent-card.json
HTTP/2 401
www-authenticate: Bearer realm="research-azure....azurecontainerapps.io"
x-ms-middleware-request-id: a2e2bf7d-458b-4197-a9ce-fae82666d986
```

There is no `server` header from the application. The response comes from the
Container Apps auth middleware, configured `unauthenticatedClientAction:
Return401`, answering on the agent's behalf.

Check the auth configuration:

```console
$ az containerapp auth show -n research-azure -g research-mesh-rg
"identityProviders": { "azureActiveDirectory": {
    "registration": { "clientId": "be143e2d-...",
                      "openIdIssuer": "https://sts.windows.net/40482c55-.../" },
    "validation": { "allowedAudiences": [ "be143e2d-..." ] } } }
```

The Agent Framework process never receives the request, so this leg contributes
a denial row rather than a card.

## Debugging API Permission Errors

Requesting a token for the Azure application from the workstation fails before
any card is fetched:

```console
$ az account get-access-token --resource be143e2d-...
ERROR: AADSTS65001: The user or administrator has not consented to use the
application with ID '04b07795-8ddb-461a-bbee-02f9e1bf7b46' named
'Microsoft Azure CLI'.
```

The workstation is signed in to the correct tenant. The Azure CLI application
has no consent to request that audience, so opening the leg requires an admin
consent grant or a client secret.

The GCP leg has a related issue. Pinning the audience is refused for a user
account:

```console
$ gcloud auth print-identity-token --audiences=https://research-gcp-...run.app
ERROR: (gcloud.auth.print-identity-token) Invalid account type for
`--audiences`. Requires valid service account.
```

The token that comes back carries `aud` set to the gcloud OAuth client id,
`32555940559.apps.googleusercontent.com`, and not the Cloud Run service URL.
Cloud Run accepts it anyway, honouring the allowlisted CLI client id. The result
proves IAM role membership only, so the tool logs a warning on every fallback.

## What Fields are Actually in the Cards?

This is the full top level field inventory across the three clouds. The spec
groups fields into required core, 1.0 era, legacy 0.x, and optional:

| category | field | Cloud Run (ADK) | AgentCore (a2a-sdk) | Container Apps |
|---|---|---|---|---|
| required | capabilities | yes | yes | no card |
| required | defaultInputModes | yes | yes | no card |
| required | defaultOutputModes | yes | yes | no card |
| required | description | yes | yes | no card |
| required | name | yes | yes | no card |
| required | skills | yes | yes | no card |
| required | version | yes | yes | no card |
| 1.0 | supportedInterfaces | yes | yes | no card |
| 1.0 | securityRequirements | no | no | no card |
| legacy 0.x | url | no | yes | no card |
| legacy 0.x | preferredTransport | no | yes | no card |
| legacy 0.x | additionalInterfaces | no | no | no card |
| legacy 0.x | security | no | no | no card |
| legacy 0.x | supportsAuthenticatedExtendedCard | no | no | no card |
| optional | protocolVersion | no | yes | no card |
| optional | documentationUrl | no | no | no card |
| optional | iconUrl | no | no | no card |
| optional | provider | no | no | no card |
| optional | securitySchemes | no | no | no card |
| optional | signatures | no | no | no card |

The Container Apps column is the honest shape of the result. Its agent answers
401 at the platform auth middleware, so there is no card to inventory and no
field in it can be reported either way.

That column is not the same as a column of noes. A no means the card was read
and the field was absent. `no card` means nothing was read at all, and every
field in that column is unknown rather than missing. Collapsing the two would
turn one denial into twenty findings.

The local mesh does not fill the gap either. Its `azure` specimen runs the
a2a-sdk reference routes rather than Agent Framework, so it is a control for the
SDK and says nothing about what the deployed Azure runtime publishes.

Three conclusions follow from the two columns that do carry a card.

## Required Fields - Where the Clouds Agree

Both cards carry all seven required fields. Neither card is malformed, and a
validator checking only the required set passes both.

Every difference between these two runtimes is in optional or legacy territory.
That is why a schema validator is not sufficient for cross cloud work, and why
the comparison has to happen at the field level.

## The 1.0 and 0.x Split

The Cloud Run card carries `supportedInterfaces` and none of the legacy keys. It
is a clean 1.0 shape.

The AgentCore card carries `supportedInterfaces` and also `url` and
`preferredTransport`, which the 1.0 spec replaced. It is a hybrid, serving both
generations at once.

A client written for 0.x reads `url` and works against AgentCore, and finds
nothing on Cloud Run. A client written for 1.0 reads `supportedInterfaces` and
works against both.

| client generation | Cloud Run | AgentCore |
|---|---|---|
| reads url | fails, key absent | works |
| reads supportedInterfaces | works | works |

The hybrid card is the more compatible of the two. It is also the one that
declares a version it does not match.

## Where is protocolVersion Declared?

The two SDKs put the protocol version in opposite places:

| location | Cloud Run (ADK) | AgentCore (a2a-sdk) |
|---|---|---|
| top level `protocolVersion` | absent | `0.3` |
| `supportedInterfaces[].protocolVersion` | `1.0` | absent |

A client that reads the top level field sees nothing from Cloud Run and `0.3`
from AgentCore. A client that reads the per interface field sees `1.0` from
Cloud Run and nothing from AgentCore.

Both readings are wrong in one direction each. The AgentCore card declares `0.3`
while carrying the 1.0 `supportedInterfaces` key, so trusting the declared value
routes a client into the wrong protocol generation.

The reliable test is structural. Branch on the presence of
`supportedInterfaces`, not on any declared version string.

## Capabilities - Absent is not False

The `capabilities` object differs by one key:

| capability | Cloud Run (ADK) | AgentCore (a2a-sdk) |
|---|---|---|
| streaming | false | false |
| pushNotifications | false | absent |
| stateTransitionHistory | absent | absent |
| extensions | absent | absent |

Cloud Run states that push notifications are unsupported. AgentCore says
nothing.

For a client these are different answers. An explicit `false` is a commitment,
and an absent key is an unknown that a strict client has to probe or assume. Two
agents with identical behaviour are described with different degrees of
confidence.

## Skills - What Counts as a Skill?

Both cards carry exactly one skill with the same four keys, and the values have
almost nothing in common:

| skill field | Cloud Run (ADK) | AgentCore (a2a-sdk) |
|---|---|---|
| id | `research_agent` | `research_brief` |
| name | `custom` | `research brief` |
| description | 69 chars, the agent description | 1,258 chars, the system prompt |
| tags | `custom_agent` | `research`, `writing`, `analysis`, `brain:llm`, `model:us.amazon.nova-micro-v1:0` |

The `id` fields name different things. ADK uses the agent name, so the skill id
and the agent name are the same string. AgentCore uses the capability name.

The `name` fields are not comparable at all. ADK emits the literal string
`custom`, which is a category rather than a label. AgentCore emits a human
readable name.

The `description` fields diverge the most. ADK repeats the agent description.
AgentCore publishes the agent's entire system prompt, 1,258 characters of
instruction text, and the tags name the model behind it.

A router selecting agents by skill description is reading a one line summary
from one cloud and a full system prompt from the other. Ranking those by text
similarity compares documents of different kinds.

## Which Fields Come from the SDK and Which from the Author?

Not every difference is the runtime's doing. The same a2a-sdk version produces
different fields in two deployments:

```console
local    aws skills[0]: description, examples, id, inputModes, name, outputModes, tags
deployed aws skills[0]: description, id, name, tags
```

The local specimen sets `examples`, `inputModes` and `outputModes`. The deployed
agent does not. `documentationUrl` behaves the same way, present locally and
absent when deployed.

So card richness has two independent sources. Structural fields such as
`protocolVersion` placement, `url` and `preferredTransport` come from the SDK.
Descriptive fields such as `examples`, `inputModes` and `documentationUrl` come
from whoever wrote the agent.

Attributing a missing `examples` array to the cloud is a mistake. Attributing a
missing `url` key to the author is also a mistake.

## What is Missing from Every Card

Six optional fields are absent from both deployed cards:

| field | what a client loses |
|---|---|
| securitySchemes | no declaration of how to authenticate |
| securityRequirements | no statement of what is required |
| provider | no organisation behind the agent |
| documentationUrl | nowhere to send a human |
| iconUrl | nothing to render in a catalogue |
| signatures | nothing binds the card to the agent it describes |

The first two matter most. Both agents return 401 or 403 without a credential,
and neither card declares a security scheme. A client that discovers either
agent learns nothing from the card about why its next request will be rejected.

The absence of `signatures` means an agent card is an unauthenticated claim. Any
party able to serve that path can assert any capability.

## What the Field Differences Mean for a Client

Collecting the field analysis into the decisions a client actually makes:

| client decision | field it reads | Cloud Run | AgentCore | safe approach |
|---|---|---|---|---|
| which protocol generation | protocolVersion | absent | 0.3, incorrect | test for supportedInterfaces |
| where to send the request | url or interfaces | 0.0.0.0:8080, unroutable | correct public URL | never route by card URL alone |
| which transport | preferredTransport | absent | JSONRPC | read protocolBinding on the interface |
| can it stream | capabilities.streaming | false | false | reliable |
| can it push | capabilities.pushNotifications | false | absent | treat absent as unknown |
| what can it do | skills[].description | one line | full system prompt | do not compare by text length |
| how do I authenticate | securitySchemes | absent | absent | out of band knowledge required |
| is this card genuine | signatures | absent | absent | not answerable |

Two of these are actively dangerous rather than merely incomplete. Routing by
the Cloud Run card URL sends traffic to `0.0.0.0:8080`. Trusting the AgentCore
declared protocol version selects 0.3 semantics for a 1.0 shaped card.

## Time to Start Comparing some Cards!

One command dials every peer, reviews each card, contrasts the results and
stores the run:

```console
$ agentcard fetch --save
run 2aca64eb85d6  3/3 card(s)  55ms

  gcp    200  1.0          675B  none              0 err  0 warn
  aws    200  hybrid       717B  none              0 err  1 warn
  azure  200  hybrid       719B  none              0 err  1 warn
```

The local mesh reproduces the same split. The gcp specimen runs google-adk and
produces the 1.0 shape. The other two run a2a-sdk and produce the hybrid shape.

The agents are identical echo agents, so the shape difference is the SDK.

## Results

Point the tool at a peers file and fetch the deployed agents:

```console
$ agentcard --corpus-dir .cards-deployed fetch --peers-file peers.toml --save
run 99f55f50b545  2/3 card(s)  24974ms

  gcp    200  1.0          528B  gcloud-id-token   1 err  2 warn
  aws    200  hybrid      2109B  aws-sigv4-local   0 err  2 warn
  azure  FAILED  authentication: 401 on /.well-known/agent-card.json
```

Two of three answered. The Azure leg stays in the corpus as a row rather than a
gap, because a blank column reads as disagreement with every other peer, which
is the opposite of what a denial means.

The run produced six findings:

| sev | peer | code | detail |
|---|---|---|---|
| error | azure | no-card | 401, the Entra app has not consented to the CLI client id |
| error | gcp | bind-address-on-card | advertises http://0.0.0.0:8080 |
| warning | gcp | plaintext-url | http:// for a remote agent |
| warning | gcp | undeclared-auth | fetched with a credential, names no securitySchemes |
| warning | aws | undeclared-auth | same, on the other cloud |
| warning | aws | version-shape-mismatch | declares 0.3, shaped like hybrid |

## A Card that Changed

Five runs of the same peer, at the same endpoint, with the same credential,
across three and a half hours:

| run | time (UTC) | version | skills | bytes |
|---|---|---|---|---|
| 8c201b95f349 | 14:10:24 | 0.0.1 | 4 | 1533 |
| 2a4992c4372b | 15:58:28 | 0.0.1 | 4 | 1533 |
| 05bb15448c63 | 16:01:04 | 0.0.1 | 4 | 1533 |
| 07f23fc6df3f | 17:17:39 | 0.0.1 | 1 | 528 |
| 6dedd20d0b05 | 17:40:46 | 0.0.1 | 1 | 528 |

Three runs sit on one side and two on the other, and each group is byte for byte
stable. The card lost two thirds of its bytes and three of its four skills, and
the `version` field did not move.

The flattened composition is what was removed:

```
05bb15448c63 -> ['research_agent',
                 'research_agent-sub-agents',
                 'research_agent_gemini_research_agent_gemini',
                 'research_agent_gemini_research_agent_gemini-web_search']

07f23fc6df3f -> ['research_agent']
```

A client that discovered this agent at 16:01 and cached "it can search the web"
held a claim the card no longer made by 17:17.

The review output is identical across the change. Diffing the two defect blocks
produces no output:

```console
$ diff <(agentcard replay 05bb15448c63) <(agentcard replay 07f23fc6df3f)
```

Both runs report 1 error and 2 warnings on this peer, and the same six defects
run wide at the same severities. A checker that asks only whether a card is
conformant reports no difference, because on that question there is none.

## Gating on Drift

Conformance and change are different questions, so they use different exit
codes:

```console
$ agentcard fetch --save --fail-on-change
$ agentcard fetch --fail-on-defect
```

Restarting a specimen so it advertises a different URL produces exit 0 from
`--fail-on-defect` and exit 4 from `--fail-on-change`.

| exit | meaning |
|---|---|
| 0 | ran, nothing gated |
| 1 | bad invocation |
| 2 | --fail-on-defect, a card is wrong now |
| 3 | no peer served a card at all |
| 4 | --fail-on-change, a card differs from the previous run |

Exit 3 is distinct from 1 and 2. A harness must separate an instrument failure
from a working instrument reporting bad news.

A peer name is not an identity. The local specimens and the deployed agents are
both named gcp, aws and azure, so a corpus holding both would compare a local
specimen against Cloud Run and report it as vendor drift. A peer whose endpoint
changed prints as `[not compared]` and does not trip the gate.

## Discovery Cost

A card fetched over a federated credential costs round trips to another cloud
identity provider first, and arrives byte identical to one fetched from an open
port:

| peer | auth | keyless | round trips | discovery ms |
|---|---|---|---|---|
| gcp (local) | none | yes | 1 | 16 |
| aws (local) | none | yes | 1 | 9 |
| azure (local) | none | yes | 1 | 6 |
| gcp (deployed) | gcloud-id-token | yes | 1 | 175 |
| aws (deployed) | aws-sigv4-local | no | 1 | 695 |
| azure (deployed) | none | yes | 1 | 25550 |

The local mesh answers in 55 ms. The deployed run takes 25 seconds, and almost
all of it is the Azure Container App cold starting to return a 401.

## Validating the Results

Each result was re-checked with curl and python3, independent of the tool:

| result | validation method | outcome |
|---|---|---|
| Two SDKs, two card shapes | curl both local cards | confirmed |
| protocolVersion in opposite places | curl, read the field | confirmed |
| Both shapes reproduce when deployed | parsed the server raw bytes | confirmed |
| Live card advertises 0.0.0.0:8080 | curl the deployed card | confirmed |
| Neither deployed card declares auth | curl and raw bytes | confirmed |
| capabilities differ by one key | field inventory across both cards | confirmed |
| skill fields carry different meanings | field inventory across both cards | confirmed |
| skill richness is author set | same SDK, two deployments | confirmed |
| A card changed with no version bump | five stored runs over 3.5 h | confirmed |
| The review did not report the change | diff of both review outputs | identical |
| The two gates catch different things | both run on one changed card | 0 vs 4 |
| replay never dials | every server killed, then replayed | confirmed |

The replay path is tested by removing the network. Stop every server, confirm
nothing is listening, then replay a run that fetched three cards:

```console
$ ss -ltn | grep -c '1100[123]'
0
$ agentcard replay
run 1657b2be9bff  3/3 card(s)  46ms
  gcp    200  1.0          675B  none              0 err  0 warn
  aws    200  hybrid       717B  none              0 err  1 warn
  azure  200  hybrid       719B  none              0 err  1 warn
```

Three cards are reviewed with every server down.

## Final Results

| approach | catches invalid cards | catches field divergence | catches drift | cost |
|---|---|---|---|---|
| read the spec | no | no | no | free |
| a JSON schema validator | yes | no | no | free |
| invoke the agent and inspect | partly | no | no | model spend |
| this harness | yes | yes | yes | zero spend |

Both deployed cards are valid. Every meaningful difference between them sits in
optional and legacy fields that a schema validator does not examine, which is
the gap a field level comparison fills.

## Summary

The goal of this article was to fetch A2A agent cards from multiple clouds and
compare the fields they publish. The key to the solution was storing the exact
bytes each server returned and comparing every field at every nesting level.
Three local specimens and three remote agents were presented, covering two A2A
SDKs and three deployment clouds. Finally, a drift gate was added to compare
each run against the previous stored corpus.

The field comparison produced these results:

- Both deployed cards carry all seven required fields, so both are valid and
  every difference sits in optional or legacy territory.
- The AgentCore card is a hybrid, carrying the 1.0 `supportedInterfaces` and the
  0.x `url` and `preferredTransport` together. The Cloud Run card is clean 1.0.
- The two SDKs declare `protocolVersion` in opposite places, and the AgentCore
  value of 0.3 contradicts the 1.0 shape of the card it appears on.
- `capabilities` differ by one key, and an absent key is not the same answer as
  an explicit false.
- The `skills` fields carry different meanings on each cloud. ADK emits the
  literal name `custom` and a one line description, and AgentCore emits a human
  name, a 1,258 character system prompt and the model id.
- Card richness has two sources. Structural fields come from the SDK, and
  descriptive fields come from the agent author.
- Six optional fields are absent from both cards, including `securitySchemes` on
  two agents that both require credentials, and `signatures` on both.
- A live card changed with no version bump, and the conformance review was
  identical on both sides of the change.

Cards change without notice and without a version bump, so every result in this
article names the date it was measured on.

The code is at
[xbill9/multicloud-agentcard](https://github.com/xbill9/multicloud-agentcard).
