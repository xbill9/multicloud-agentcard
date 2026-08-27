# multicloud-agentcard

Pull A2A agent cards from remote native agents and read what comes back.

Forked from [multicloud-a2a-subagent](https://github.com/xbill9/multicloud-a2a-subagent),
which sends a research brief to three agents on three clouds and judges the
drafts. This repo keeps that project's credential seam and wire tracer and
throws away everything downstream of the handshake. **It never invokes
anything.** It fetches the card, keeps the bytes, and asks two questions:

1. Is this card *correct* — does it conform, and can a client act on it?
2. Are these cards *the same* — and where they differ, what does that cost
   whoever writes the client?

The second question is the one worth the repo. Every card in a corpus can be
perfectly conformant and still leave a client author with five branches to
write, because the spec permits all five.

---

## What it found in its first hour

Two A2A serving stacks, on one laptop, describing the same trivial echo agent.
Measured 2026-08-24 against `a2a-sdk` 1.1.2 and `google-adk` 2.6.3.

**They do not agree on what an agent card looks like, and they do not agree on
where the protocol version goes.**

| axis | gcp (ADK `to_a2a`) | aws / azure (`a2a-sdk` routes) |
|---|---|---|
| card revision, read off the keys | `1.0` | hybrid |
| `protocolVersion` at the top level | absent | `"0.3"` |
| `protocolVersion` per interface | `"1.0"` | absent |
| top-level `url` | absent | present, duplicating `supportedInterfaces[0].url` |

`a2a-sdk` serves a **hybrid**: it emits 1.0's `supportedInterfaces` list and
then back-fills `url`, `preferredTransport` and `protocolVersion: "0.3"`
alongside it. So the card declares 0.3 while carrying 1.0's shape. ADK does the
opposite — pure 1.0 structure, nothing declared at the top level, and the
version written *inside* each interface entry, where it says `1.0`.

The consequence is concrete and it is why this is a `warning` and not a note:
**a client that branches on `protocolVersion` gets the wrong answer for both
stacks.** Read the top level and ADK's cards look undeclared while a2a-sdk's
claim a revision they are not shaped like. Read the interfaces and a2a-sdk's
look undeclared. Branch on the presence of `supportedInterfaces` instead —
which is what `cards/spec.py` does, and why it reports the declared version and
the inferred shape as two separate columns.

Neither stack signs its card. Neither declares a security scheme. Both leave
`provider` and `iconUrl` empty. Those are notes, not defects — and they are the
answer to "what do these runtimes have in common", which is also worth having.

### The deployed three, measured 2026-08-25

All three, from a workstation. The gap below turned out to be narrower than it
read: only the *workload* mint needs a metadata server, and all three clouds
will accept a credential a laptop can produce. See **Reaching the deployed
three** for what that does and does not prove.

```
run 23cff0f73098  3/3 card(s)  17660ms

  gcp    200  1.0          528B  gcloud-id-token   1 err  2 warn
  aws    200  hybrid      2109B  aws-sigv4-local   0 err  2 warn
  azure  200  hybrid      1924B  entra-fic         0 err  2 warn
```

The full report is `docs/deployed-2026-08-25.md`, the findings are written up in
`docs/DISCOVERY-FINDINGS.md`, and `docs/ARTICLE.md` is the write-up of the whole
run. Three headlines:

- **Both shapes reported above off the local specimens reproduce when
  deployed.** Cloud Run/ADK serves a 1.0-shaped card; AgentCore and Container
  Apps serve hybrids declaring `0.3`. ADK's `0.0.0.0:8080` bind address is
  still on the live card, and it is the only error in the run.
- **AgentCore and Container Apps are field-identical.** Every top-level key,
  every skill key, the same `version` `0.1.0`, the same skill id, the same
  1,258-character skill description. The only differences anywhere in the two
  cards are the two hostnames and one tag value. Two clouds and two agent
  frameworks, one shape — because both frameworks hand card construction to the
  same `a2a-sdk` route helper, which is what the shape tracks. Nothing here
  separates the framework from the SDK: no framework in this mesh appears on
  two SDKs.
- **That gcp card is 528B; the same peer served 1533B at 14:10 the same day**,
  with `version` unmoved at `0.0.1`. A Cloud Run revision created between the
  two readings is the cause; `docs/ARTICLE.md` has the series.

### What has *still* not been measured

**The workload mint.** Nothing here has fetched a card using the
metadata-server credentials the deployed coordinator actually uses. Every
reading above was taken in a workstation mode, and the report names that mode on
every row so the two can never be read as one result.

**The AWS role trust policy.** `aws-sigv4-local` reads keys off the disk and
signs with them, so it proves the caller holds
`bedrock-agentcore:GetAgentCard` and proves nothing about
`AssumeRoleWithWebIdentity` or the conditions on that role.

The Entra credential is the one trust policy a workstation does exercise: the
FIC pins `sub` to a service account's numeric id, and impersonation produces a
token carrying exactly that subject.

---

## Using it

```bash
uv pip install --system -e '.[specimens,dev]'      # no virtualenv, see CLAUDE.md
pyenv rehash                                       # if `agentcard` is not found

./infra/run_mesh.sh start          # three local specimens on :11001 :11002 :11003
agentcard fetch --save             # dial them, review, contrast, store
./infra/run_mesh.sh stop
```

`python3 -m cards.cli` is the same program and always works, installed or not.

Run it as a gate, which is the point of storing anything:

```bash
agentcard fetch --save --fail-on-change     # exit 4 if any card moved
agentcard fetch --fail-on-defect            # exit 2 if any card is wrong
agentcard diff --fail-on-change             # exit 4, over the stored corpus
```

The two gates catch opposite things and neither substitutes for the other. A
**defect** is a card that is wrong now. **Drift** is a card that differs from
the one this project last read — and a runtime moving `0.3` to `1.0` between
two deploys, with every check still green, is the event `CLAUDE.md` says this
repo exists to catch. Measured, and re-run 2026-08-27: change a specimen's
advertised URL and `--fail-on-defect` exits `0` while `--fail-on-change` exits
`4` and names the fields.

Drift is measured against the **last saved run**, so `--save` accepts the
current cards as the new baseline. Without it the same drift is re-reported
every run until something stores it.

**A corpus holds one mesh.** `--corpus-dir` exists for this: the local
specimens live in `.cards/` (the default) and the deployed three in
`.cards-deployed/`. Interleaving them in one directory makes the drift baseline
alternate between two different meshes, so every other run compares a laptop
specimen against Cloud Run:

```bash
agentcard fetch --save                                     # local
# --corpus-dir is a global flag: it goes before the subcommand, not after.
agentcard --corpus-dir .cards-deployed fetch --peers-file peers.toml --save
```

**A peer name is not an identity.** The local specimens and the deployed agents
are both called `gcp`, `aws` and `azure`, so a corpus holding both would diff a
laptop specimen against Cloud Run and call it vendor drift — measured on
2026-08-25, four fields on two peers, exit 4, with nothing in the output able
to say the two runs were of different servers. That is the same failure as the
health check in `CLAUDE.md`'s opening. A peer whose **endpoint** moved is now
printed as `[not compared]`, names both endpoints, and never trips the gate:
the card of a different server is not a changed card.

| exit | meaning |
|---|---|
| 0 | ran, nothing gated |
| 1 | bad invocation — a peer list that will not assemble, a run id that names nothing |
| 2 | `--fail-on-defect`: a card has an error-severity finding |
| 3 | **no peer served a card at all** |
| 4 | `--fail-on-change`: a card differs from the previous stored run |

`3` is separate from `1` and `2` on purpose. A harness has to be able to tell
*the instrument failed* from *the instrument worked and the news is bad*, and
"every peer refused" is the first of those however green the checks are.

```
run 8859a97fa522  3/3 card(s)  53ms

  gcp    200  1.0          675B  none              0 err  0 warn
  aws    200  hybrid       717B  none              0 err  1 warn
  azure  200  hybrid       719B  none              0 err  1 warn

contrast: 4 client-visible difference(s)
  protocolVersion as declared:
    gcp    -
    aws    0.3
    azure  0.3
  protocolVersion declared per interface:
    gcp    1.0
    aws    -
    azure  -
  ...
```

Anything else, with no code change:

```bash
agentcard fetch --peer demo=https://example.org/agent,auth=none
agentcard fetch --peers-file peers.toml --markdown report.md --json run.json
```

```toml
[[peer]]
name = "gcp"
endpoint = "https://research-gcp-wgcq55zbfq-uc.a.run.app"
runtime = "Cloud Run / ADK to_a2a"
auth = "google-id-token"
```

Naming a peer suppresses the built-in three, deliberately: a run against one
public agent must not silently dial two clouds nobody asked about. `--builtin
aws` brings one back.

### Everything else works offline

`fetch` is the only subcommand that touches the network.

```bash
agentcard replay --markdown report.md   # re-review the last run, no network
agentcard show gcp --raw                # the bytes exactly as served
agentcard diff                          # what changed since the run before
agentcard history
```

That split is load-bearing. Iterating on the review logic against a stored
corpus is how the checks get written, and a `replay` that re-fetched could
change what a past run "found".

Exit codes are tabled under **Using it**: `0` fine, `1` bad invocation, `2`
`--fail-on-defect`, `3` no peer served a card, `4` `--fail-on-change`.

---

## How it is put together

```
peers/     who to reach, and what to prove on the way
  aws_origin.py, errors.py                       carried over verbatim
  auth.py      carried over, plus the two workstation modes this fork needed
  trace.py     carried over, plus the discovery/invoke rule for prefixed paths
  registry.py                                    new: peers are data, not code

cards/     fetch -> review -> compare -> report
  fetch.py    what came back, byte for byte, and what it cost to get it
  spec.py     what a card is supposed to look like, per revision
  review.py   what one card says, measured against that
  compare.py  where the cards disagree with each other
  report.py   markdown and terminal, one renderer
  store.py    a dated corpus, so "did this change" is answerable

agents/    two a2a-sdk specimens and one ADK specimen, locally, as the control
```

**The credential is attached to the httpx client, not to a request.** The card
fetch has to be authenticated in its own right, not as a side effect of the call
it is preparing for. On AgentCore that is literal — `GetAgentCard` is a separate
IAM action from `InvokeAgentRuntime` — so a policy granting only the second
denies the card fetch while the call it was preparing for would have succeeded,
and the denial surfaces as a transport or protocol error nowhere near auth.
Cloud Run and Container Apps do not separate the two (see **Reaching the
deployed three**); the seam is written to the strictest of the three. See
`docs/DISCOVERY-FINDINGS.md`.

**Two local stacks, on purpose.** ADK's `to_a2a()` builds its own app and its
own card with no way to say what goes on it; the other two sit on the a2a-sdk
reference routes. Having both on the bench is what tells a *runtime* difference
from an *SDK* difference when the deployed cards are read.

### Severity means something

`error` — a client that follows the card is broken by it.
`warning` — the card is usable and something about it will cost someone an afternoon.
`note` — a true observation with no defect attached.

Notes are where the compare-and-contrast lives. They are separated from defects
so the defects stay findable, not so the notes can be filtered away.

---

## Reaching the deployed three

Open, and the honest state of it. The three agents answer 403, 403 and 401 to
anyone without a credential — measured 2026-08-25, re-checked 2026-08-27 — and
that is the deployment, not an accident of it. The parent reaches them from a
coordinator on Cloud Run:

| leg | mechanism |
|---|---|
| → GCP | Google ID token, `roles/run.invoker` |
| → AWS | metadata mint → STS `AssumeRoleWithWebIdentity` → SigV4 |
| → Azure | Entra Federated Identity Credential on `accounts.google.com` |

All three start from a **workload** OIDC token minted at the GCE metadata
server, and a workstation has none.

### What a workstation can already reach (2026-08-25)

All three, with three modes added for them. Each is a **weaker measurement**
than the workload path, and the report names the mode on every row so the two
can never be read as the same result.

| leg | workstation mode | what it proves | what it does not |
|---|---|---|---|
| → GCP | `gcloud-id-token` | the developer has `roles/run.invoker` | nothing about the coordinator's service account |
| → AWS | `aws-sigv4-local` | `~/.aws/credentials` has `bedrock-agentcore:GetAgentCard` | nothing about the role trust policy |
| → Azure | `entra-fic` + `<NAME>_A2A_IMPERSONATE` | the FIC's subject condition accepts that service account | nothing about the mint the assertion normally comes from |

```bash
agentcard fetch --peers-file peers.toml --save     # peers.toml is gitignored
```

Two measured details that make `gcloud-id-token` less obvious than it looks:

- **A user account cannot pin the audience.** `gcloud auth print-identity-token
  --audiences=<url>` is refused outright — *"Invalid account type for
  `--audiences`. Requires valid service account."* So the token carries
  `aud` = gcloud's own OAuth client id `32555940559.apps.googleusercontent.com`,
  not the service URL.
- **Cloud Run accepts it anyway.** The invoker check honours Google's
  allowlisted CLI client id. The mode therefore proves IAM role membership and
  **not** that any audience condition holds — which is exactly the confusion
  `peers/auth.py` logs a warning about every time it falls back.

`aws-sigv4-local` reuses the same `_sign_request` as the federated mode and
swaps only the origin of the key. It is deliberately **not** in `KEYLESS_MODES`:
it mints nothing, so it looks keyless, but what it reads off the disk is very
often a static access key and it cannot tell which it got.

**Azure took an impersonation to open, and stayed keyless.** Its Container App
is configured `unauthenticatedClientAction: Return401` against app registration
`be143e2d-…`. That registration exposes no API scopes and pre-authorizes no
application, so minting a token for it as a user fails `AADSTS65001: the user or
administrator has not consented` — and it holds exactly one federated
credential, which is the whole allowlist:

```
issuer     https://accounts.google.com
subject    1049501159…              <- a GCP service account's numeric id
audiences  api://AzureADTokenExchange
```

One identity, on one other cloud, can read this agent's card. A workstation can
still *become* that identity, because impersonation produces a token carrying
the service account's `sub` rather than the developer's:

```bash
gcloud auth print-identity-token \
  --impersonate-service-account=research-coordinator@…iam.gserviceaccount.com \
  --audiences=api://AzureADTokenExchange --include-email
```

That needs `roles/iam.serviceAccountTokenCreator` on the target account. Project
Owner is **not** sufficient — Owner does not carry
`iam.serviceAccounts.getAccessToken`. Set `<NAME>_A2A_IMPERSONATE` and
`credentials_for` wires that identity into `EntraFederatedAuth`, which exchanges
the assertion at Entra for `<client-id>/.default` unchanged. The card comes back
200, 1,924 bytes, two round trips. No client secret, so the leg stays in
`KEYLESS_MODES` honestly.

Two ways to the *workload* path, and they are not equivalent:

1. **Run `agentcard fetch` on Cloud Run**, as the parent's coordinator does.
   Unchanged credentials, unchanged trust policies, and the cards it fetches
   are the ones a real caller sees. Not yet done.
2. **Impersonate the coordinator's service account locally**, which is what the
   Azure leg above does. Faster, and it changes what is being measured: the
   trust conditions on the AWS and Entra legs pin the *subject* to that service
   account's immutable numeric ID, so an impersonated token satisfies them where
   a developer's own cannot. Whatever comes back must be labelled as fetched
   under impersonation — which is why `entra-fic` is printed on the azure row of
   every report.

Either way `peers/auth.py` needs no change. `credentials_for` already takes an
explicit mode so a peers file can configure this per peer.

---

## Testing

```bash
python3 -m pytest -q      # 125 passed
ruff check .              # all checks passed
```

Hermetic. The fetcher's transport is injectable, so the suite covers the cases
a live cloud will not produce on demand — a card served only on the 0.2 path, a
403 carrying a real AgentCore denial, a 200 carrying an HTML login page.

Two things in the suite are worth knowing about:

- **`tests/corpus/` holds real cards.** `adk.json` and `a2a-sdk.json` are what
  the two stacks actually served on 2026-08-24, kept whole. Every fixture is
  derived from them. Inventing a card to test a check against is how a check
  ends up correct about a card no runtime emits.
- **`test_sdk_fields_are_all_in_the_table`** re-derives 1.0's field names from
  the installed `a2a-sdk` proto and asserts this repo knows all of them. When
  the spec moves, a field this repo has never heard of would be reported to
  every user as a vendor extension — a wrong answer with no symptom. That test
  turns it into a red test on the next install.

### The ports are 11001-11003, and that is a finding

The parent repo runs three agents on 10001-10003. This fork's first card
comparison was **of the parent's agents**: its own specimens had failed to bind
with "address already in use", and `run_mesh.sh` reported all three ready
because its health check reached the other project's servers. Nothing in the
output could have said so.

Two projects, two port ranges — and `run_mesh.sh` now checks that its own
process survived before it calls anything ready. A start that cannot tell whose
server it reached is not a start.
