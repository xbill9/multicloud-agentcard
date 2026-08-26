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

## How is Discovery Privileged Against Invocation?

Differently on each cloud, and the three answers do not resemble each other:

| cloud | what gates the card | separable from invocation |
|---|---|---|
| Bedrock AgentCore | `bedrock-agentcore:GetAgentCard` | yes, a distinct IAM action |
| Cloud Run | `roles/run.invoker` | no, the same role invokes |
| Container Apps | platform auth on every path | no, and not configurable per path here |

Only AgentCore lets you grant discovery without granting invocation. On Cloud
Run the card and the call sit behind one role, so anything that can read the
card can also run the agent. On Container Apps the platform intercepts every
path ahead of the container, which is stricter still and is covered later.

The AgentCore case is the one that produces a confusing failure. A policy
granting only `InvokeAgentRuntime` denies the card fetch, and the denial
surfaces as a transport or protocol error nowhere near auth.

This is why the credential is attached to the httpx client rather than to a
single request: the card fetch needs authenticating in its own right, not as a
side effect of the call it is preparing for.

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

The Azure agent runs on Container Apps behind the platform's built-in auth.
Fetching the card without a credential returns a 401:

```console
$ curl -s -D - https://research-azure....azurecontainerapps.io/.well-known/agent-card.json
HTTP/2 401
www-authenticate: Bearer realm="research-azure....azurecontainerapps.io"
x-ms-middleware-request-id: a2e2bf7d-458b-4197-a9ce-fae82666d986
```

There is no `server` header from the application. The response comes from the
Container Apps auth middleware, not from the agent.

The request never reaches the container. Two requests, one to the card path and
one to `/health`, both returned 401, and uvicorn logged neither:

```console
$ az containerapp logs show -n research-azure -g research-mesh-rg --tail 40
"F INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)"
```

The app is up and serving. It registers the card route through the same a2a-sdk
helper the AWS agent uses. The 401 is interception, not absence.

With a credential the card is 1,924 bytes:

```json
{
  "name": "research_agent",
  "description": "An agent that writes a short, sourced research brief on a given topic",
  "supportedInterfaces": [{ "url": "https://research-azure....azurecontainerapps.io",
                            "protocolBinding": "JSONRPC" }],
  "version": "0.1.0",
  "capabilities": { "streaming": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [{ "id": "research_brief", "name": "research brief",
               "description": "You are a research assistant with a web_search
                               tool...",
               "tags": ["research","writing","analysis","brain:llm",
                        "model:research-reasoning"] }],
  "preferredTransport": "JSONRPC",
  "protocolVersion": "0.3",
  "url": "https://research-azure....azurecontainerapps.io"
}
```

Note the interface URL. Container Apps sits behind a platform ingress exactly as
Cloud Run does, and this card advertises the routable public hostname.

## Debugging API Permission Errors

Requesting a token for the Azure application from the workstation fails before
any card is fetched:

```console
$ az account get-access-token --resource be143e2d-...
ERROR: AADSTS65001: The user or administrator has not consented to use the
application with ID '04b07795-8ddb-461a-bbee-02f9e1bf7b46' named
'Microsoft Azure CLI'.
```

The workstation is signed in to the correct tenant, so this is not a missing
login. The app registration exposes no API scopes, has no identifier URIs and
no pre-authorized applications, which means no user and no other application can
obtain a token for it at all.

It holds exactly one credential, and that is the whole allowlist:

```console
$ az ad app federated-credential list --id be143e2d-...
  issuer    https://accounts.google.com
  subject   1049501159…            <- a GCP service account numeric id
  audiences api://AzureADTokenExchange
```

That subject is the numeric id of a GCP service account. One identity on one
other cloud can read this agent's card.

A workstation can still become that identity, because impersonation produces a
token carrying the service account's `sub` rather than the developer's:

```console
$ gcloud auth print-identity-token \
    --impersonate-service-account=research-coordinator@...iam.gserviceaccount.com \
    --audiences=api://AzureADTokenExchange --include-email
```

That needs `roles/iam.serviceAccountTokenCreator` on the target. Project Owner
is not sufficient, because Owner does not include
`iam.serviceAccounts.getAccessToken`. Exchange the result at the Entra token
endpoint for `<client-id>/.default` and the card returns 200.

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

| category | field | Cloud Run (ADK) | AgentCore (a2a-sdk) | Container Apps (Agent Framework) |
|---|---|---|---|---|
| required | capabilities | yes | yes | yes |
| required | defaultInputModes | yes | yes | yes |
| required | defaultOutputModes | yes | yes | yes |
| required | description | yes | yes | yes |
| required | name | yes | yes | yes |
| required | skills | yes | yes | yes |
| required | version | yes | yes | yes |
| 1.0 | supportedInterfaces | yes | yes | yes |
| 1.0 | securityRequirements | no | no | no |
| legacy 0.x | url | no | yes | yes |
| legacy 0.x | preferredTransport | no | yes | yes |
| legacy 0.x | additionalInterfaces | no | no | no |
| legacy 0.x | security | no | no | no |
| legacy 0.x | supportsAuthenticatedExtendedCard | no | no | no |
| optional | protocolVersion | no | yes | yes |
| optional | documentationUrl | no | no | no |
| optional | iconUrl | no | no | no |
| optional | provider | no | no | no |
| optional | securitySchemes | no | no | no |
| optional | signatures | no | no | no |

Read the last two columns again. AgentCore and Container Apps agree on every
single row.

That holds all the way down. Same `capabilities` keys, same skill keys, same
interface keys, the same `version` string `0.1.0`, the same skill id
`research_brief`, and the same 1,258 character skill description. The only
differences anywhere in the two cards are the hostnames and one tag value:
`model:us.amazon.nova-micro-v1:0` against `model:research-reasoning`.

Those are two different clouds running two different agent frameworks. Strands
on AgentCore, Microsoft Agent Framework on Container Apps. They emit
structurally identical cards because both hand card construction to the same
a2a-sdk route helper.

Cloud Run is the only column that differs, and it differs on every structural
row. ADK does not delegate; `to_a2a()` builds its own card.

That is the honest width of this result. What varies with the cloud is nothing;
what varies is whether the framework builds the card itself or delegates. Two
delegating frameworks agreeing does not prove the framework is irrelevant, since
neither is doing the work. Separating the two properly would need one framework
across two SDKs, or a non-delegating framework on two clouds, and neither is in
this mesh.

## Required Fields - Where the Clouds Agree

All three cards carry all seven required fields. None is malformed, and a
validator checking only the required set passes all three.

Every difference between these runtimes is in optional or legacy territory. That
is why a schema validator is not sufficient for cross cloud work, and why the
comparison has to happen at the field level.

## The 1.0 and 0.x Split

The Cloud Run card carries `supportedInterfaces` and none of the legacy keys. It
is a clean 1.0 shape.

The AgentCore and Container Apps cards carry `supportedInterfaces` and also
`url` and `preferredTransport`, which the 1.0 spec replaced. Both are hybrids,
serving two generations at once.

A client written for 0.x reads `url`, works against two of the three clouds, and
finds nothing on Cloud Run. A client written for 1.0 reads `supportedInterfaces`
and works everywhere.

| client generation | Cloud Run | AgentCore | Container Apps |
|---|---|---|---|
| reads url | fails, key absent | works | works |
| reads supportedInterfaces | works | works | works |

The hybrid cards are the more compatible of the two shapes. They are also the
ones declaring a version they do not match.

## Where is protocolVersion Declared?

The two SDKs put the protocol version in opposite places:

| location | Cloud Run (ADK) | AgentCore | Container Apps |
|---|---|---|---|
| top level `protocolVersion` | absent | `0.3` | `0.3` |
| `supportedInterfaces[].protocolVersion` | `1.0` | absent | absent |

A client that reads the top level field sees nothing from Cloud Run and `0.3`
from the other two. A client that reads the per interface field sees `1.0` from
Cloud Run and nothing from the other two.

Both readings are wrong in one direction each. Two of the three cards declare
`0.3` while carrying the 1.0 `supportedInterfaces` key, so trusting the declared
value routes a client into the wrong protocol generation on two clouds.

The reliable test is structural. Branch on the presence of
`supportedInterfaces`, not on any declared version string.

## Capabilities - Absent is not False

The `capabilities` object differs by one key:

| capability | Cloud Run (ADK) | AgentCore | Container Apps |
|---|---|---|---|
| streaming | false | false | false |
| pushNotifications | false | absent | absent |
| stateTransitionHistory | absent | absent | absent |
| extensions | absent | absent | absent |

Cloud Run states that push notifications are unsupported. The other two say
nothing.

For a client these are different answers. An explicit `false` is a commitment,
and an absent key is an unknown that a strict client has to probe or assume.
Three agents with identical behaviour are described with different degrees of
confidence.

## Skills - What Counts as a Skill?

All three cards carry exactly one skill with the same four keys. Two of the
three agree on every value; the third has almost nothing in common with them:

| skill field | Cloud Run (ADK) | AgentCore | Container Apps |
|---|---|---|---|
| id | `research_agent` | `research_brief` | `research_brief` |
| name | `custom` | `research brief` | `research brief` |
| description | 69 chars, the agent description | 1,258 chars, the system prompt | 1,258 chars, the system prompt |
| tags | `custom_agent` | `research`, `writing`, `analysis`, `brain:llm`, `model:us.amazon.nova-micro-v1:0` | `research`, `writing`, `analysis`, `brain:llm`, `model:research-reasoning` |

The `id` fields name different things. ADK uses the agent name, so the skill id
and the agent name are the same string. The other two use the capability name.

The `name` fields are not comparable at all. ADK emits the literal string
`custom`, which is a category rather than a label. The other two emit a human
readable name.

The `description` fields diverge the most. ADK repeats the agent description.
The other two publish the agent's entire system prompt, 1,258 characters of
instruction text, and their tags name the model behind it.

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

The first two matter most. All three agents reject unauthenticated requests, and
not one card declares a security scheme. A client that discovers any of these
agents learns nothing from the card about why its next request will be rejected.
This is unanimous across three clouds, three frameworks and two SDKs.

The absence of `signatures` means an agent card is an unauthenticated claim. Any
party able to serve that path can assert any capability.

## What the Field Differences Mean for a Client

Collecting the field analysis into the decisions a client actually makes:

| client decision | field it reads | Cloud Run | AgentCore | Container Apps | safe approach |
|---|---|---|---|---|---|
| which protocol generation | protocolVersion | absent | 0.3, incorrect | 0.3, incorrect | test for supportedInterfaces |
| where to send the request | url or interfaces | 0.0.0.0:8080, unroutable | correct public URL | correct public URL | never route by card URL alone |
| which transport | preferredTransport | absent | JSONRPC | JSONRPC | read protocolBinding on the interface |
| can it stream | capabilities.streaming | false | false | false | reliable |
| can it push | capabilities.pushNotifications | false | absent | absent | treat absent as unknown |
| what can it do | skills[].description | one line | full system prompt | full system prompt | do not compare by text length |
| how do I authenticate | securitySchemes | absent | absent | absent | out of band knowledge required |
| is this card genuine | signatures | absent | absent | absent | not answerable |

Two of these are actively dangerous rather than merely incomplete. Routing by
the Cloud Run card URL sends traffic to `0.0.0.0:8080`. Trusting the declared
protocol version selects 0.3 semantics for a 1.0 shaped card, on two clouds.

The bind address row also settles a question the single cloud view cannot.
Container Apps sits behind a platform ingress exactly as Cloud Run does, and it
advertises the routable hostname. The unroutable URL is ADK's doing, not a
consequence of being deployed behind an ingress.

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
run 23cff0f73098  3/3 card(s)  17660ms

  gcp    200  1.0          528B  gcloud-id-token   1 err  2 warn
  aws    200  hybrid      2109B  aws-sigv4-local   0 err  2 warn
  azure  200  hybrid      1924B  entra-fic         0 err  2 warn
```

Three clouds, three cards. The run produced seven findings:

| sev | peer | code | detail |
|---|---|---|---|
| error | gcp | bind-address-on-card | advertises http://0.0.0.0:8080 |
| warning | gcp | plaintext-url | http:// for a remote agent |
| warning | gcp | undeclared-auth | fetched with a credential, names no securitySchemes |
| warning | aws | undeclared-auth | same, on the second cloud |
| warning | aws | version-shape-mismatch | declares 0.3, shaped like hybrid |
| warning | azure | undeclared-auth | same, on the third cloud |
| warning | azure | version-shape-mismatch | declares 0.3, shaped like hybrid |

The only error belongs to one cloud. The two hybrid cards produce identical
findings as well as identical fields.

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

The cause is a deployment, and the platform will tell you so:

```console
$ gcloud run revisions list --service=research-gcp --region=us-central1
NAME                    CREATION_TIMESTAMP
research-gcp-00020-6hd  2026-08-25T17:08:19Z
research-gcp-00019-dq6  2026-08-14T19:20:15Z
```

Revision 00020 was created at 17:08:19, between the last four skill reading at
16:01 and the first one skill reading at 17:17. The revision before it was
eleven days old. The agent was redeployed with different composition, which is
ordinary and expected.

So this is not a card mutating on its own, and it would be wrong to read it that
way. What it does show is narrower and still worth having: **a redeploy changed
the card materially while `version` stayed at `0.0.1`.** A client cannot use
`version` to decide whether a card it cached is still current, because the field
does not track the content. That is an agent authoring gap rather than a
platform or protocol one, and it is invisible from the card alone.

Checking the revision list is one command, and it is the difference between
reporting a fact and reporting a mechanism. Any drift a corpus catches should be
matched against the platform's own deployment history before it is called
anything stronger than a change.

The flattened composition is what was removed:

```
05bb15448c63 -> ['research_agent',
                 'research_agent-sub-agents',
                 'research_agent_gemini_research_agent_gemini',
                 'research_agent_gemini_research_agent_gemini-web_search']

07f23fc6df3f -> ['research_agent']
```

A client that discovered this agent at 16:01 and cached "it can search the web"
held a claim the card no longer made by 17:17, and nothing in the card told it
so. The redeploy is the explanation; it is not the excuse, because a client has
no way to see a redeploy.

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
| gcp (deployed) | gcloud-id-token | yes | 1 | 16785 |
| aws (deployed) | aws-sigv4-local | no | 1 | 771 |
| azure (deployed) | entra-fic | yes | 2 | 683 |

The local mesh answers in 55 ms. The deployed run is dominated by whichever
container is cold, and the Azure leg costs two round trips rather than one
because the Google assertion has to be exchanged at Entra before the card can be
requested.

## Validating the Results

Each result was re-checked with curl and python3, independent of the tool:

| result | validation method | outcome |
|---|---|---|
| Two SDKs, two card shapes | curl both local cards | confirmed |
| protocolVersion in opposite places | curl, read the field | confirmed |
| Both local shapes reproduce when deployed | parsed the server raw bytes | confirmed |
| Live card advertises 0.0.0.0:8080 | curl the deployed card | confirmed |
| No deployed card declares auth | curl and raw bytes | confirmed |
| capabilities differ by one key | field inventory across all three cards | confirmed |
| skill fields carry different meanings | field inventory across all three cards | confirmed |
| skill richness is author set | same SDK, two deployments | confirmed |
| AgentCore and Container Apps are field identical | full field inventory of both cards | confirmed |
| The Azure app serves a card | 200 with an impersonated federated token | confirmed |
| The Azure 401 is interception, not absence | 2 requests, 401 each, zero uvicorn log lines | confirmed |
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

All three deployed cards are valid. Every meaningful difference sits in optional
and legacy fields that a schema validator does not examine, which is the gap a
field level comparison fills.

The three way result is sharper than a two way one. Two clouds and two agent
frameworks produced structurally identical cards, and the third differed on
every structural row. Across this mesh the card shape tracks the card builder,
not the cloud: the two frameworks that delegate to a2a-sdk agree exactly, and
the one that builds its own card is the outlier on every structural row.

## Summary

The goal of this article was to fetch A2A agent cards from multiple clouds and
compare the fields they publish. The key to the solution was storing the exact
bytes each server returned and comparing every field at every nesting level.
Three local specimens and three remote agents were presented, covering three
deployment clouds, three agent frameworks and two A2A SDKs. Finally, a drift
gate was added to compare each run against the previous stored corpus.

The field comparison produced these results:

- All three deployed cards carry the seven required fields, so all three are
  valid and every difference sits in optional or legacy territory.
- AgentCore and Container Apps emit structurally identical cards. Same fields,
  same version string, same skill id, same 1,258 character description. Two
  clouds and two agent frameworks, one shape.
- Cloud Run is the outlier on every structural row, and it is the only card
  carrying an error.
- Across this mesh the shape tracks the card builder rather than the cloud. Both
  identical cards come from frameworks that delegate to a2a-sdk; the outlier
  builds its own. Whether the framework matters independently of that is not
  separable here, because no framework appears on two SDKs.
- The two SDKs declare `protocolVersion` in opposite places, and the `0.3` on
  the two hybrid cards contradicts the 1.0 shape they carry.
- `capabilities` differ by one key, and an absent key is not the same answer as
  an explicit false.
- ADK emits the literal skill name `custom` and a 69 character description. The
  other two emit a human name, the agent's full system prompt and the model id.
- Not one card declares `securitySchemes`, though all three reject
  unauthenticated requests.
- A redeploy changed a card from four skills to one while `version` stayed at
  `0.0.1`, and the conformance review was identical on both sides. The cause was
  a Cloud Run revision created between the two readings, not a card mutating on
  its own; the point is that `version` does not track content, so a client
  cannot use it to tell whether a cached card is current.

Discovery is privileged differently on each cloud, and the range is wide. Cloud
Run gates the card behind an invoker role. AgentCore makes discovery a
separately grantable IAM action. Container Apps intercepts every path at the
platform, so the card is readable only by the single federated identity the app
registration trusts, and a client must already hold the credential before it can
read the document describing which credential to use.

## What this does not establish

One agent per runtime, one region per cloud, one tenant, and a single reading of
each card apart from the Cloud Run series. Two SDKs and three frameworks, with
no framework appearing on more than one SDK.

So the field differences are properties of these deployments on this date. They
are not a survey of what Cloud Run, AgentCore or Container Apps do in general,
and the two identical cards agree because of a shared card builder rather than
anything the clouds have in common.

The field categories used throughout come from this repo's model of the spec in
`cards/spec.py`, not from an independent conformance suite. A field sorted into
the wrong category there would move consistently across every table here.

Cards change across deploys without the `version` field moving, so every result
in this article names the date it was measured on.

The code is at
[xbill9/multicloud-agentcard](https://github.com/xbill9/multicloud-agentcard).
