# Working notes for this repo

Forked from [multicloud-a2a-subagent](https://github.com/xbill9/multicloud-a2a-subagent)
on 2026-08-24. That repo sends one research brief to three native agents on
three clouds, judges the drafts, and audits the result. **This one stops at
discovery.** It fetches agent cards and reads them; it never invokes anything.

The ground rules below are inherited because they were paid for, not because
they were copied.

## Ground rule: deploy, then document

Do not write article or results content for a path that has not been deployed
and exercised end to end. Code-complete plus a green local suite is not a
result.

This repo's own first hour is the argument. The card fetcher was working, the
suite was green, and the first comparison it produced was **of the wrong
agents** — the local specimens had failed to bind because the parent repo's
mesh was already on those ports, and `run_mesh.sh` reported all three ready
because its health check reached the other project's servers. Nothing in the
output could have said so. The ports moved to 11001-11003 and the start script
now checks that its own process survived.

The rule has a second half here that the parent did not need. **A finding
about a vendor's card must name the date and the version it was measured on.**
A card changes materially while `version` stays put — measured 2026-08-25, when
the Cloud Run card went from four skills to one and `version` did not move off
`0.0.1` — so the field does not track the content, and a claim that does not
say when it was true is a claim that quietly becomes false.

**Match any drift against the platform's own deployment history before calling
it more than a change.** That series reads as a card mutating on
its own until `gcloud run revisions list` names the revision created between the
two readings. A corpus sees the change; only the platform explains it.

**A transcript in a document is the command's real output, re-run.** Not its
summary, not the part of it that made the point. A `diff` printed with
nothing under it, when the command as written exits 1, is a claim any reader
falsifies in one paste.

And the parent's most expensive lesson, unchanged: **work that is deployed but
not committed does not exist.**

## Ground rule: commit straight to master

**Never create a branch and never open a pull request.** Small single-author
project. Commit to `master` and push. Do not offer a branch, do not ask whether
one would be preferable, and do not treat "you are on the default branch" as a
reason to hesitate — here it is the only branch, by choice.

## Ground rule: no virtualenvs, latest everything

**Never create or use a virtualenv.** No `uv venv`, no `python -m venv`, no
`.venv`. Install to the system interpreter with `uv pip install --system` and
run with `python3 -m pytest`.

**Use the latest version of every package, runtime, and compiler**, and when
the latest stack breaks something, fix what broke. Pinning back is not a fix,
it is a deferral. The one legitimate reason to pin is a **measured** failure
you cannot fix from here, and such a pin owes a comment naming the failure and
a re-test whenever the area is touched.

Nothing in this repo is pinned.

## Ground rule: store the bytes, derive everything else

A `Specimen` holds the exact body the server sent. Every later step — the
conformance review, the cross-peer contrast, the report — is a pure function of
that body plus its HTTP metadata. Parsing on the way in would be convenient and
would throw away the finding: a field a vendor spells differently, an extra key
no client models, a body that is not JSON at all.

Two consequences worth defending:

- **`replay` must never dial anything.** Iterating on the review logic against
  a stored corpus is how the checks get written; a `replay` that re-fetched
  could change what a past run "found".
- **A card that did not arrive is a row, not a gap.** It stays in the corpus,
  it leads the report, and it is excluded from the contrast tables — because a
  blank column reads as "this peer disagrees with everyone", which is the
  opposite of what a denial means.

## Where the value is: notes, not errors

The severity split in `cards/review.py` is `error` / `warning` / `note`, and
**`note` is where the compare-and-contrast actually lives.** Vendor extensions,
absent optional fields, transports outside the spec's list — none of them are
defects and all of them are the answer to "what is different about these
runtimes". Notes are separated from defects so the defects stay findable, not
so the notes can be filtered away. Do not let a future change treat the note
count as noise to be driven to zero.

## Auth: what came across, and what did not

`peers/auth.py`, `peers/aws_origin.py` and `peers/trace.py` are carried over
**verbatim**. Every comment in them is a defect somebody paid for. The
constraints that cost real time in the predecessor series still hold:

- **Audience alone is not authorization.** Also pin the subject, using the
  immutable numeric ID rather than an email.
- **AWS federates with `accounts.google.com` natively**; creating an explicit
  IAM OIDC provider for it *breaks* federation. For Entra you must create one.
- **The IAM condition keys do not mean what they are named.**
  `accounts.google.com:oaud` is the token's `aud`; `accounts.google.com:aud` is
  the token's `azp`.
- **`format=full`** on the GCP metadata mint, or Google omits the `email` claim.
- **Diagnostic:** `InvalidIdentityToken` means the token could not be validated
  at all; `AccessDenied` means your trust conditions did not match.
- **Log the raw provider response at every auth boundary.** The raised message
  is not an observable. Raise *and* log.

One thing changed, and it is the shape of the fork. The parent ran on Cloud
Run, which can mint workload OIDC tokens for an arbitrary audience. **This is a
CLI on a laptop, and a laptop has no metadata server.** `credentials_for` now
takes an explicit `mode` so a peers file can configure two peers that want the
same mode with different parameters. The mint itself is unchanged, and on
2026-08-25 all three deployed cards were fetched from this workstation:
`gcloud-id-token`, `aws-sigv4-local`, and `entra-fic` over an impersonated
service-account assertion (`<NAME>_A2A_IMPERSONATE`).

What that does *not* reach is the workload mint the deployed coordinator uses,
or the AWS role trust policy, which `aws-sigv4-local` steps around by reading
keys off the disk. The Entra FIC is the one trust policy a workstation does
exercise, because it pins `sub` to a service account's numeric id and
impersonation produces exactly that subject. The README keeps the state of each
leg.

## Discovery is privileged separately from invocation — on one cloud of three

Measured 2026-08-25, and the three answers do not resemble each other:

- **Bedrock AgentCore** — `bedrock-agentcore:GetAgentCard`, a distinct IAM
  action. Discovery is grantable without invocation.
- **Cloud Run** — `roles/run.invoker` gates the card, and that role also
  invokes.
- **Container Apps** — platform auth intercepts every path ahead of the
  container, and is not configured per path here.

Only AgentCore separates them, and it is the one that produces a confusing
failure: a policy granting only `InvokeAgentRuntime` denies the card fetch, and
the denial surfaces as a transport or protocol error, nowhere near auth.

This is why the credential is attached to the httpx **client** and not to one
request. The card fetch has to be authenticated in its own right rather than as
a side effect of the call it is preparing for, and the seam is written to the
strictest of the three.

In this repo that stops being an aside and becomes the whole subject.
