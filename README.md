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

Two of them, from a workstation, with the third recorded as a denial row. The
gap below turned out to be narrower than it read: only the *federated* path
needs a metadata server, and two of the three clouds will accept a credential a
laptop can already produce. See **Reaching the deployed three** for what that
does and does not prove.

```
run 8c201b95f349  2/3 card(s)  5126ms

  gcp    200  1.0         1533B  gcloud-id-token   1 err  2 warn
  aws    200  hybrid      2109B  aws-sigv4-local   0 err  2 warn
  azure  FAILED  authentication: 401 on /.well-known/agent-card.json
```

The full report is `docs/deployed-2026-08-25.md`, and the findings are written
up in `docs/DISCOVERY-FINDINGS.md`. The headline: **the two shapes reported
above off the local specimens reproduce on the deployed pair** — Cloud Run/ADK
serves a 1.0-shaped card, AgentCore a hybrid one declaring `0.3` — and ADK's
`0.0.0.0:8080` bind address is still on the live card.

### What has *still* not been measured

**The Azure leg.** Container Apps returns 401 and its Entra app registration
has not consented to the Azure CLI's client id, so `az account get-access-token`
against it fails `AADSTS65001` before any card is fetched. It stays in the
corpus as a denial row rather than a blank column.

**Anything through the federated path.** Nothing here has yet fetched a card
using the workload credentials the deployed coordinator actually uses, so no
claim in this repo tests those trust policies.

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

Exit codes: `0` fine, `1` bad invocation, `2` with `--fail-on-defect` when a
card has an error-severity finding, `3` when no peer served a card at all.

---

## How it is put together

```
peers/     who to reach, and what to prove on the way
  auth.py, aws_origin.py, trace.py, errors.py   carried over verbatim
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

**The credential is attached to the httpx client, not to a request.** Discovery
is privileged separately from invocation on all three clouds — on AWS it is
literally a different IAM action, `bedrock-agentcore:GetAgentCard` — so a card
fetch that carries no credential 403s while the call it was preparing for would
have succeeded. That failure surfaces as a transport or protocol error, nowhere
near auth. See `docs/DISCOVERY-FINDINGS.md`.

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

Open, and the honest state of it. The three agents answer 401/403 to anyone
without a federated credential — that is the deployment, and it is the point.
The parent reaches them from a coordinator on Cloud Run:

| leg | mechanism |
|---|---|
| → GCP | Google ID token, `roles/run.invoker` |
| → AWS | metadata mint → STS `AssumeRoleWithWebIdentity` → SigV4 |
| → Azure | Entra Federated Identity Credential on `accounts.google.com` |

All three start from a **workload** OIDC token minted at the GCE metadata
server, and a workstation has none.

### What a workstation can already reach (2026-08-25)

Two of the three, with two modes added for it. Both are **weaker measurements**
than the federated path and the report names the mode on every row so the two
can never be read as the same result.

| leg | workstation mode | what it proves | what it does not |
|---|---|---|---|
| → GCP | `gcloud-id-token` | the developer has `roles/run.invoker` | nothing about the coordinator's service account |
| → AWS | `aws-sigv4-local` | `~/.aws/credentials` has `bedrock-agentcore:GetAgentCard` | nothing about the role trust policy |
| → Azure | — | — | 401; see below |

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

**Azure is still shut.** Its Container App is configured
`unauthenticatedClientAction: Return401` against app registration
`be143e2d-…`, and minting a token for that audience from the CLI fails
`AADSTS65001: the user or administrator has not consented`. Opening it means an
admin consent grant on someone's tenant, or a client secret — the one mode in
this repo that is not keyless. Neither is a thing to do quietly, so the leg
stays a denial row.

Two ways forward for the *federated* path, and they are not equivalent:

1. **Run `agentcard fetch` on Cloud Run**, as the parent's coordinator does.
   Unchanged credentials, unchanged trust policies, and the cards it fetches
   are the ones a real caller sees.
2. **Impersonate the coordinator's service account locally.** Faster, and it
   changes what is being measured: the trust conditions on the AWS and Entra
   legs pin the *subject* to that service account's immutable numeric ID, so an
   impersonated token may satisfy them while a developer's own token cannot.
   Whatever comes back must be labelled as fetched under impersonation.

Either way `peers/auth.py` needs no change. `credentials_for` already takes an
explicit mode so a peers file can configure this per peer.

---

## Testing

```bash
python3 -m pytest -q      # 110 passed
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
