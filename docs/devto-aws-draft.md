---
title: What Bedrock AgentCore Actually Puts on Your A2A Agent Card
published: false
description: The agent card a Strands agent publishes on Bedrock AgentCore, compared field by field against Cloud Run and Azure Container Apps.
tags: aws, bedrock, a2a, aiagents
cover_image: https://raw.githubusercontent.com/xbill9/multicloud-agentcard/master/docs/article-header.jpg
---

This article provides a step by step look at the A2A agent card a Strands agent
publishes on Amazon Bedrock AgentCore Runtime, and how it compares field by
field against the same agent on Google Cloud Run and Azure Container Apps.

The code is here:

[github.com/xbill9/multicloud-agentcard](https://github.com/xbill9/multicloud-agentcard)

Same Protocol - Different Cards!

Why do I care what is in the Agent Card? Can't I just invoke the Agent?

## What is this Approach actually Comparing?

This project fetches the agent card from every agent in a mesh, stores the exact
bytes each server sent, and compares the fields side by side.

It never invokes anything. There is no model, no prompt and no token spend in
the measurement path. It stops at discovery.

The AWS leg is a Strands agent on Bedrock AgentCore Runtime in us-west-2. The
other two legs are a Google ADK agent on Cloud Run and a Microsoft Agent
Framework agent on Azure Container Apps. All results below were measured on
2026-08-25.

## Discovery is its own IAM Action

This is the AgentCore detail that costs the most time if you meet it the hard
way. Fetching an agent card is **not** covered by `InvokeAgentRuntime`:

```json
{
  "Action": ["bedrock-agentcore:InvokeAgentRuntime",
             "bedrock-agentcore:GetAgentCard"],
  "Resource": ["arn:aws:bedrock-agentcore:us-west-2:...:runtime/<id>",
               "arn:aws:bedrock-agentcore:us-west-2:...:runtime/<id>/*"]
}
```

A policy granting only `InvokeAgentRuntime` denies the card fetch however the
resources are written. Scoping to the runtime ARN and its children works once
`GetAgentCard` is present, so there is no need for a wildcard resource.

The failure this produces is confusing because it surfaces nowhere near auth. A
credential that reaches the call and fails on the card looks like a transport or
protocol error to the client. This is why the credential belongs on the HTTP
client rather than on a single request.

AgentCore is the only one of the three clouds that makes discovery separately
grantable. That is a feature, and it is worth knowing you have it.

## The Card Lives Under the Invocation Path

AgentCore has no per-agent hostname. The runtime is addressed by URL escaped
ARN, and the card sits beneath the same `/invocations/` path the calls use:

```
bedrock-agentcore.us-west-2.amazonaws.com
  /runtimes/arn%3Aaws%3Abedrock-agentcore%3A...%3Aruntime%2Fresearch_aws-...
  /invocations/.well-known/agent-card.json
```

Cloud Run and Container Apps both publish at the well known path on their own
hostname. AgentCore does not, and that has a consequence for tooling.

Any tracer that classifies a round trip as discovery only when the path
**equals** a known card path, or **begins with** `/.well-known/`, will file
every AgentCore card fetch as an invocation. Match on the suffix instead. Our
own tracer had this bug, and it mislabelled every AWS card fetch until the rule
was fixed.

AgentCore also requires its session header on the card fetch, not just on calls:

```
X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: <at least 33 characters>
```

It must fall inside the SigV4 signature, so set it before signing.

## Checking the Runtime

List the runtime and confirm it is ready:

```console
$ aws bedrock-agentcore-control list-agent-runtimes --region us-west-2
[ { "name": "research_aws",
    "arn": "arn:aws:bedrock-agentcore:us-west-2:...:runtime/research_aws-...",
    "status": "READY" } ]
```

## Fetching the Card

The fetcher signs with SigV4 and stores the exact bytes that came back:

```console
$ agentcard --corpus-dir .cards-deployed fetch --peers-file peers.toml --save
run 23cff0f73098  3/3 card(s)  17660ms

  gcp    200  1.0          528B  gcloud-id-token   1 err  2 warn
  aws    200  hybrid      2109B  aws-sigv4-local   0 err  2 warn
  azure  200  hybrid      1924B  entra-fic         0 err  2 warn
```

The AgentCore card is the largest of the three at 2,109 bytes, four times the
size of the Cloud Run card for the same logical agent.

## What AgentCore Publishes

Here is the card:

```json
{
  "capabilities": { "streaming": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "description": "An agent that writes a short, sourced research brief",
  "name": "research_agent",
  "preferredTransport": "JSONRPC",
  "protocolVersion": "0.3",
  "skills": [{ "description": "<the agent's full system prompt, 1,258 chars>",
               "id": "research_brief", "name": "research brief",
               "tags": ["research","writing","brain:llm",
                        "model:us.amazon.nova-micro-v1:0"] }],
  "supportedInterfaces": [{ "protocolBinding": "JSONRPC",
                            "url": "<the runtime invocations endpoint>" }],
  "url": "<the runtime invocations endpoint>",
  "version": "0.1.0"
}
```

Read the `skills` entry again. The description is the agent's **entire system
prompt**, 1,258 characters of instruction text, and the tags name the model
behind it.

That is not a bug in AgentCore. It is what the a2a-sdk card builder does with a
Strands agent's system prompt, and it is worth knowing before you ship. The
agent card is the document you hand to anyone who can call `GetAgentCard`. On
this stack it carries your prompt and your model id.

If neither should be public, set the skill description explicitly rather than
letting it default from the agent's instructions.

## Where AgentCore Sits Against the Other Two

This is the full top level field inventory across the three clouds:

| category | field | AgentCore | Cloud Run (ADK) | Container Apps |
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
| legacy 0.x | url | yes | no | yes |
| legacy 0.x | preferredTransport | yes | no | yes |
| legacy 0.x | additionalInterfaces | no | no | no |
| legacy 0.x | security | no | no | no |
| legacy 0.x | supportsAuthenticatedExtendedCard | no | no | no |
| optional | protocolVersion | yes | no | yes |
| optional | documentationUrl | no | no | no |
| optional | iconUrl | no | no | no |
| optional | provider | no | no | no |
| optional | securitySchemes | no | no | no |
| optional | signatures | no | no | no |

AgentCore and Container Apps agree on every row.

That holds all the way down. Same `capabilities` keys, same skill keys, same
interface keys, the same `version` string `0.1.0`, the same skill id
`research_brief`, and the same 1,258 character description. The only differences
anywhere are the hostnames and one tag value.

Those are two different clouds running two different agent frameworks, Strands
on AgentCore and Microsoft Agent Framework on Container Apps. They emit
structurally identical cards because both serve through the same a2a-sdk route
helper. **The card shape follows the serving SDK, not the cloud and not the
agent framework.**

## The AgentCore Card is the More Compatible One

AgentCore carries `supportedInterfaces` and also `url` and `preferredTransport`,
which the 1.0 spec replaced. It is a hybrid, serving two generations at once.
Cloud Run carries only `supportedInterfaces`.

| client generation | AgentCore | Cloud Run | Container Apps |
|---|---|---|---|
| reads url | works | fails, key absent | works |
| reads supportedInterfaces | works | works | works |

A client written for 0.x works against AgentCore and finds nothing on Cloud Run.
That makes the AgentCore card the more compatible of the two shapes.

It is also the one declaring a version it does not match, which is the next
section.

## The protocolVersion Trap

The two SDKs put the protocol version in opposite places:

| location | AgentCore | Cloud Run (ADK) | Container Apps |
|---|---|---|---|
| top level `protocolVersion` | `0.3` | absent | `0.3` |
| `supportedInterfaces[].protocolVersion` | absent | `1.0` | absent |

AgentCore declares `0.3` at the top level while carrying the 1.0
`supportedInterfaces` key. A client that trusts the declared value selects 0.3
semantics for a card that is shaped like 1.0.

Read the top level and the ADK card looks undeclared. Read the interfaces and
the AgentCore card looks undeclared. Both readings are wrong in one direction
each.

The reliable test is structural. Branch on the presence of
`supportedInterfaces`, not on any declared version string.

## Where AgentCore Wins

The run produced seven findings and not one of them is AgentCore's:

| sev | peer | code | detail |
|---|---|---|---|
| error | gcp | bind-address-on-card | advertises the bind address `0.0.0.0:8080` |
| warning | gcp | plaintext-url | http:// for a remote agent |
| warning | gcp | undeclared-auth | names no securitySchemes |
| warning | aws | undeclared-auth | names no securitySchemes |
| warning | aws | version-shape-mismatch | declares 0.3, shaped like hybrid |
| warning | azure | undeclared-auth | names no securitySchemes |
| warning | azure | version-shape-mismatch | declares 0.3, shaped like hybrid |

The only error belongs to Cloud Run. ADK's `to_a2a()` writes its bind address
onto the card, so a public HTTPS endpoint advertises `0.0.0.0:8080` over plain
http to every client that routes by card URL.

AgentCore advertises its real, routable endpoint. So does Container Apps. Both
sit behind a platform ingress, which settles that the unroutable URL is ADK's
doing rather than a consequence of being deployed behind one.

## What Every Card is Missing

Six optional fields are absent from all three:

| field | what a client loses |
|---|---|
| securitySchemes | no declaration of how to authenticate |
| securityRequirements | no statement of what is required |
| provider | no organisation behind the agent |
| documentationUrl | nowhere to send a human |
| iconUrl | nothing to render in a catalogue |
| signatures | nothing binds the card to the agent it describes |

The first two matter most for AgentCore specifically. Your agent requires SigV4
and the `GetAgentCard` action, and the card says nothing about either. A client
that discovers your agent learns nothing from the card about why its next
request will be rejected.

The absence of `signatures` means an agent card is an unauthenticated claim.
Anything able to serve that path can assert any capability.

## Discovery Cost

| peer | auth | round trips | discovery ms |
|---|---|---|---|
| aws (AgentCore) | aws-sigv4-local | 1 | 771 |
| gcp (Cloud Run) | gcloud-id-token | 1 | 16785 |
| azure (Container Apps) | entra-fic | 2 | 683 |

AgentCore answers in one round trip. The Azure leg costs two because a Google
assertion has to be exchanged at Entra first. The Cloud Run number is a cold
start, not a steady state.

## Catching a Card That Moved

The corpus is dated, which makes one more question answerable: did this card
change? Five runs of the Cloud Run peer over three and a half hours:

| run | time (UTC) | version | skills | bytes |
|---|---|---|---|---|
| 8c201b95f349 | 14:10:24 | 0.0.1 | 4 | 1533 |
| 2a4992c4372b | 15:58:28 | 0.0.1 | 4 | 1533 |
| 05bb15448c63 | 16:01:04 | 0.0.1 | 4 | 1533 |
| 07f23fc6df3f | 17:17:39 | 0.0.1 | 1 | 528 |
| 6dedd20d0b05 | 17:40:46 | 0.0.1 | 1 | 528 |

The card lost three of its four skills and the `version` field did not move. The
conformance review is identical on both sides of the change, so a checker that
asks only whether a card is valid reports no difference.

Conformance and change are different questions, so they get different exit
codes. `--fail-on-defect` exits 2 and `--fail-on-change` exits 4.

## Summary

The goal of this article was to fetch the A2A agent card a Strands agent
publishes on Bedrock AgentCore and compare it field by field against two other
clouds. The key to the solution was storing the exact bytes each server returned
and comparing every field at every nesting level.

The AgentCore results were:

- Discovery is a separately grantable IAM action, `GetAgentCard`. A policy with
  only `InvokeAgentRuntime` denies the card fetch, and the failure surfaces
  nowhere near auth.
- The card lives beneath the `/invocations/` path rather than at a hostname
  root, which breaks any tracer that matches the well known path by prefix.
- The card publishes the agent's entire system prompt as the skill description,
  1,258 characters, and names the model in the tags.
- It is a hybrid shape, carrying both `supportedInterfaces` and the 0.x `url`,
  which makes it the more compatible of the two shapes in the mesh.
- It declares `protocolVersion` `0.3` while carrying a 1.0 shaped card, so
  branch on structure rather than on the declared version.
- It advertises a routable public endpoint, and it carries none of the run's
  errors.
- It is field identical to the same agent on Azure Container Apps, because both
  serve through a2a-sdk. The card shape follows the serving SDK, not the cloud.

Cards change without notice and without a version bump, so every result in this
article names the date it was measured on.
