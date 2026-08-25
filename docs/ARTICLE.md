# Cross Cloud A2A Agent Card Discovery

Building an Agent Card Reader with A2A - This tutorial aims to fetch and compare
agent cards from A2A agents deployed across several mainstream Cloud providers.

Same Protocol - Different Cards!

Why would I need to read the Agent Card? Can't I just call the Agent?

What is this Approach actually Comparing?

## What is this Approach actually Comparing?

This project fetches the agent card from every agent in a mesh, stores the exact
bytes each server sent, and reads them side by side.

It never invokes anything. There is no model, no prompt and no token spend in
the measurement path. It stops at discovery.

The comparison targets are three local specimens on 127.0.0.1 and three deployed
agents on Cloud Run, Bedrock AgentCore and Azure Container Apps. All results
below were measured on 2026-08-25.

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

There is no virtualenv and nothing is pinned.

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

The versions in use are a2a-sdk 1.1.2, google-adk 2.6.3, httpx 0.28.1 and
starlette 1.3.1, on Python 3.13.14.

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
something answers on the port. A health check alone reports only that some
server answered, and sharing a port range with another project produces three
ready agents and a comparison of the wrong ones.

## A2A Agent Card (google-adk Local)

The first specimen runs google-adk `to_a2a()`. Retrieve the card directly:

```console
$ curl -s http://127.0.0.1:11001/.well-known/agent-card.json
{
  "capabilities": { "pushNotifications": false, "streaming": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "description": "A minimal A2A agent that exists to be discovered...",
  "name": "card_specimen",
  "skills": [{ "description": "A minimal A2A agent...",
               "id": "card_specimen", "name": "custom",
               "tags": ["custom_agent"] }],
  "supportedInterfaces": [{ "protocolBinding": "JSONRPC",
                            "protocolVersion": "1.0",
                            "url": "http://127.0.0.1:11001" }],
  "version": "0.0.1"
}
```

Note the placement of `protocolVersion`. It appears inside the interface entry
and nowhere else.

## A2A Agent Card (a2a-sdk Local)

The second specimen runs the a2a-sdk reference routes. The same agent behaviour
produces a different card:

```console
$ curl -s http://127.0.0.1:11002/.well-known/agent-card.json
{
  "capabilities": { "streaming": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "description": "A minimal A2A agent that exists to be discovered",
  "documentationUrl": "https://github.com/xbill9/multicloud-agentcard",
  "name": "card_specimen",
  "preferredTransport": "JSONRPC",
  "protocolVersion": "0.3",
  "skills": [{ "description": "Return the text it was given, unchanged",
               "examples": ["ping"], "id": "echo", "name": "echo",
               "tags": ["echo", "diagnostic", "cloud:aws"] }],
  "supportedInterfaces": [{ "protocolBinding": "JSONRPC",
                            "url": "http://127.0.0.1:11002" }],
  "url": "http://127.0.0.1:11002",
  "version": "1.0.0"
}
```

Here `protocolVersion` appears at the top level and is absent from the
interface. The two SDKs declare it in opposite places.

This card also carries four keys the ADK card does not have at all: `url`,
`preferredTransport`, `documentationUrl` and `protocolVersion`.

## So What is all this Doing?

The fetcher stores the exact body each server sent. Every later step is a
function of those bytes plus the HTTP metadata.

Parsing early discards the finding. A field a vendor spells differently, an
extra key no client models, or a body that is not JSON at all survives as
evidence only when the bytes are kept.

Findings are split into three severities:

| severity | meaning | example |
|---|---|---|
| error | the card is wrong now | bind-address-on-card |
| warning | legal, but a client will trip on it | version-shape-mismatch |
| note | true, not a defect, and the comparison itself | version-per-interface |

Notes are separated from defects so the defects stay findable.

## A2A Agent Card (Cloud Run / google-adk)

The deployed GCP agent runs on Cloud Run behind IAM. Retrieve the endpoint and
fetch the card with an identity token:

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

Inspecting the card shows the interface URL:

```console
  supportedInterfaces url  : ['http://0.0.0.0:8080']
  securitySchemes present  : False
  top-level protocolVersion: None
  per-interface version    : ['1.0']
```

`to_a2a()` writes the bind address onto the card. On Cloud Run the process binds
`0.0.0.0:8080`, so a public HTTPS endpoint advertises unroutable plaintext to
every client that routes by card URL.

This does not reproduce on a local mesh, where the bind address and the dial
address are the same. It requires a deployment.

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

The path shape has a consequence for any tracer. A round trip classified as
discovery only when the path equals a known card path, or begins with
`/.well-known/`, will file every AgentCore card fetch as an invocation. The rule
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

The Agent Framework process never receives the request. Its card producer is
taken from the deployment configuration.

## Debugging API Permission Errors

Requesting a token for the Azure application from the workstation fails before
any card is fetched:

```console
$ az account get-access-token --resource be143e2d-...
ERROR: AADSTS65001: The user or administrator has not consented to use the
application with ID '04b07795-8ddb-461a-bbee-02f9e1bf7b46' named
'Microsoft Azure CLI'.
```

This is not a missing credential. The workstation is signed in to the correct
tenant. The Azure CLI application has no consent to request that audience, so
opening the leg requires an admin consent grant or a client secret.

The GCP leg has a related issue. Pinning the audience is refused for a user
account:

```console
$ gcloud auth print-identity-token --audiences=https://research-gcp-...run.app
ERROR: (gcloud.auth.print-identity-token) Invalid account type for
`--audiences`. Requires valid service account.
```

The token that comes back carries `aud` set to the gcloud OAuth client id,
`32555940559.apps.googleusercontent.com`, and not the Cloud Run service URL.
Cloud Run accepts it anyway, honouring the allowlisted CLI client id.

The card arrives and the audience condition is never checked. The result proves
IAM role membership only, so the tool logs a warning naming this on every
fallback.

| workstation mode | what it proves | what it does not prove |
|---|---|---|
| gcloud-id-token | the developer holds roles/run.invoker | anything about the coordinator service account |
| aws-sigv4-local | that identity holds GetAgentCard | anything about the role trust policy |

## Time to Start Comparing some Cards!

One command dials every peer, reviews each card, contrasts the results and
stores the run:

```console
$ agentcard fetch --save
run 207a39c27e0c  3/3 card(s)  58ms

  gcp    200  1.0          675B  none              0 err  0 warn
  aws    200  hybrid       717B  none              0 err  1 warn
  azure  200  hybrid       719B  none              0 err  1 warn
```

Three agents produced two card shapes. The agents are identical echo agents, so
the difference is the SDK.

## Review the Contrast

The contrast block reports client visible differences:

```console
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

The two version rows reverse exactly. A client that branches on
`protocolVersion` gets the wrong answer for both stacks, in opposite directions.

Reading the top level makes the ADK card appear undeclared. Reading the
interfaces makes the a2a-sdk card appear undeclared. The a2a-sdk card also
declares 0.3 while carrying the 1.0 `supportedInterfaces` key.

The tool reports the declared version and the inferred shape as two separate
columns for this reason.

Field presence across the mesh shows where a client needs a fallback:

| top-level key | gcp | aws | azure |
|---|---|---|---|
| capabilities | yes | yes | yes |
| description | yes | yes | yes |
| skills | yes | yes | yes |
| supportedInterfaces | yes | yes | yes |
| version | yes | yes | yes |
| documentationUrl | no | yes | yes |
| preferredTransport | no | yes | yes |
| protocolVersion | no | yes | yes |
| url | no | yes | yes |

## Results

Point the tool at a peers file and fetch the deployed agents:

```console
$ agentcard --corpus-dir .cards-deployed fetch --peers-file peers.toml --save
run 07f23fc6df3f  2/3 card(s)  25594ms

  gcp    200  1.0          528B  gcloud-id-token   1 err  2 warn
  aws    200  hybrid      2109B  aws-sigv4-local   0 err  2 warn
  azure  FAILED  authentication: 401 on /.well-known/agent-card.json
```

Two of three answered. The Azure leg stays in the corpus as a row rather than a
gap, because a blank column reads as disagreement with every other peer, which
is the opposite of what a denial means.

The deployed run produced six findings:

| sev | peer | code | detail |
|---|---|---|---|
| error | azure | no-card | 401, the Entra app has not consented to the CLI client id |
| error | gcp | bind-address-on-card | advertises http://0.0.0.0:8080 |
| warning | gcp | plaintext-url | http:// for a remote agent |
| warning | gcp | undeclared-auth | fetched with a credential, names no securitySchemes |
| warning | aws | undeclared-auth | same, on the other cloud |
| warning | aws | version-shape-mismatch | declares 0.3, shaped like hybrid |

## Cross Checking the Deployed Cards

Both card shapes from the local mesh reproduce on the deployed pair. The shapes
are a property of the SDK, not of the specimen code:

| peer | runtime | shape | protocolVersion top level | per interface |
|---|---|---|---|---|
| gcp | Cloud Run / ADK to_a2a | 1.0 | absent | 1.0 |
| aws | Bedrock AgentCore / a2a-sdk | hybrid | 0.3 | absent |

The largest contrast in the run is what each runtime considers a skill. The same
logical agent writes a short sourced research brief.

google-adk publishes the agent description as one skill, 69 characters long:

```json
"skills": [{ "id": "research_agent", "name": "custom",
             "tags": ["custom_agent"] }]
```

a2a-sdk on AgentCore publishes the entire system prompt as the skill
description, 1,258 characters, and names the model in the tags:

```json
"skills": [{ "id": "research_brief", "name": "research brief",
             "description": "You are a research assistant with a web_search
                             tool. Given a topic, you write one short research
                             brief and nothing else...",
             "tags": ["research","writing","analysis","brain:llm",
                      "model:us.amazon.nova-micro-v1:0"] }]
```

The card is served to any caller that can reach discovery. On this runtime it
carries the prompt and the model id.

Neither card declares a `securitySchemes` block, and both require a credential.
A client that discovers either agent learns nothing from the card about why its
next request will be rejected.

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

This is a step change, not a transient. Three runs sit on one side and two on
the other, and each group is byte for byte stable.

The card lost two thirds of its bytes and three of its four skills. The
`version` field did not move.

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
run wide at the same severities. The error is the pre-existing
bind-address-on-card, which is true of both cards.

A checker that asks only whether a card is conformant reports no difference,
because on that question there is none. The card with one skill is exactly as
conformant as the card with four.

## Gating on Drift

Conformance and change are different questions, so they use different exit
codes:

```console
$ agentcard fetch --save --fail-on-change
$ agentcard fetch --fail-on-defect
```

Neither gate substitutes for the other. Restarting a specimen so it advertises a
different URL produces exit 0 from `--fail-on-defect` and exit 4 from
`--fail-on-change`.

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

The local mesh answers in 56 ms. The deployed run takes 25.6 seconds, and 25.5
of those are the Azure Container App cold starting to return a 401.

Card sizes vary by 4x across runtimes serving the same agent: 528 bytes from ADK
on Cloud Run and 2,109 bytes from AgentCore.

## Validating the Results

Each result was re-checked with curl and python3, independent of the tool:

| result | validation method | outcome |
|---|---|---|
| Two SDKs, two card shapes | curl both local cards | confirmed |
| protocolVersion in opposite places | curl, read the field | confirmed |
| Both shapes reproduce when deployed | parsed the server raw bytes | confirmed |
| Live card advertises 0.0.0.0:8080 | curl the deployed card | confirmed |
| Neither deployed card declares auth | curl and raw bytes | confirmed |
| The runtimes disagree on skill | raw bytes, field by field | confirmed |
| A card changed with no version bump | five stored runs over 3.5 h | confirmed |
| The review did not report the change | diff of both review outputs | identical |
| The two gates catch different things | both run on one changed card | 0 vs 4 |
| replay never dials | every server killed, then replayed | confirmed |
| A peer name is not an identity | local run diffed against deployed run | not gated |

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

Two conditions apply when reproducing this. Assert that every peer returned a
card before reading a gate, since a specimen that is not yet serving records a
real no-card error. And replay operates only on stored runs, so the preceding
fetch must use `--save`.

## Final Results

| approach | catches invalid cards | catches vendor drift | needs the agent running | cost |
|---|---|---|---|---|
| read the spec | no | no | no | free |
| a JSON schema validator | yes | no | no | free |
| invoke the agent and inspect | partly | no | yes | model spend |
| this harness | yes | yes | yes, discovery only | zero spend |

The drift column separates them. Every other approach reports no change on the
card that lost three skills.

The A2A protocol is consistent enough that all five cards parse. The runtimes
built on top of it are not consistent about what a card contains, where the
protocol version is declared, or what counts as a skill.

## Summary

The goal of this article was to fetch and compare A2A agent cards across
multiple clouds and identify where the runtimes disagree. The key to the
solution was storing the exact bytes each server returned and deriving every
later step from them. Three local specimens and three remote agents were
presented, covering two A2A SDKs and three deployment clouds. Finally, a drift
gate was added to compare each run against the previous stored corpus.

The results were:

- Two SDKs produce two card shapes, and both reproduce on real deployments.
- The two SDKs declare protocolVersion in opposite places, so a client branching
  on that field is wrong for both stacks.
- Two of three clouds are reachable from a workstation, and the report names the
  credential mode on every row.
- The runtimes disagree about what a skill is. ADK flattens its composition tree
  onto the card, and AgentCore publishes the system prompt and the model id.
- A live card changed with no version bump, and the conformance review was
  identical on both sides of the change.
- Azure remains closed, because its Entra app has not consented to the CLI
  client id.

Cards change without notice and without a version bump, so every result in this
article names the date it was measured on.

The code is at
[xbill9/multicloud-agentcard](https://github.com/xbill9/multicloud-agentcard).
