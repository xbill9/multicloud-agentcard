# Publishing the article

Two drafts, one source of prose.

| file | venue | tables | multi-line code |
|---|---|---|---|
| `devto-draft.md` | dev.to | markdown, rendered natively | fenced blocks |
| `medium-draft.md` | Medium | 13 images | 18 images |

`ARTICLE.md` is the working copy. `devto-draft.md` is that file plus dev.to
front matter. `medium-draft.md` is generated:

```bash
python3 docs/make_medium.py
```

Regenerate after editing the article, or the two drift.

## Why the Medium version is different

Every item below was measured on 2026-08-23 against the real importer and is
recorded at length in the predecessor repo's `docs/MEDIUM-PUBLISHING.md`. Each
one cost at least one wasted import, and several fail **silently**, which is
what makes them expensive.

- **Markdown tables do not render at all.** A pasted one becomes a wall of pipe
  characters. Every table is an image.
- **`<pre>` is flattened to a single line and `<br>` is stripped**, so
  multi-line code cannot survive as text. Every multi-line block is an image.
  Single-line blocks are left inline; there is nothing in a one-line `curl` to
  flatten.
- **Two heading sizes only.** `#` and `##` both become the large one, so section
  headings are emitted as `####`. Left as `##`, a 27-section article reads as 27
  titles.
- **A link inside a `<figcaption>` makes Medium drop the whole figure**, with no
  error and no placeholder. Captions are plain text and any link goes in a
  paragraph after the figure.
- **The importer caches by URL and ignores the query string.** `?v=2` does not
  defeat it. If a page is re-imported after a change, give the importer a
  content-addressed filename it has never seen.
- **`<link rel="canonical">` is resolved by the importer**, so a canonical
  pointing at a stable page serves that page's cached copy whatever URL was
  submitted. Strip it from the copy handed to the importer.

Two more, measured here on 2026-08-25 against the live importer, both silent:

- **A `<figure>` nested inside a `<p>` loses every figure.** python-markdown
  wraps a standalone image line in a paragraph, so substituting the `<img>` in
  place produces `<p><figure>...</figure></p>`. That nesting is invalid, a
  parser closes the paragraph at the figure's start tag, and the importer
  discards what is left. Two imports arrived with the prose and all 54 headings
  intact and **all 31 figures missing**. `make_import.py` matches the whole
  enclosing paragraph for this reason.
- **An unbalanced bracket in alt text drops that one image.** The generated alt
  `Code: 05bb15448c63 -> ['research_agent',` stops python-markdown treating the
  reference as an image at all, so it stays literal text and no figure is
  emitted. One figure of 32 went missing this way, and nothing in the markdown
  looks wrong. `make_medium.py` now strips brackets and parentheses from
  generated alt text.

Counting figures in Medium's editor needs care. The editor lazy-loads and
virtualises, so DOM counts lie until the whole document has been scrolled. And
imported content is served from `0*` image URLs while Medium's own editor chrome
is `1*`, so count only `0*` or the onboarding overlay inflates the total.

Images are the one thing Medium handles well. It fetches them, rehosts at 800px,
and takes `<figcaption>` as the caption. The **first image in the body becomes
the story's cover**, which is why the header image is the first line after the
title. Alt text survives the import and is worth writing.

## The two dev.to variants

| file | venue | angle |
|---|---|---|
| `devto-draft.md` | dev.to, personal | the three way comparison, no cloud favoured |
| `devto-aws-draft.md` | dev.to, AWS Community Builders | the same measurements led from AgentCore |

Same numbers, different lead. The AWS variant opens on `GetAgentCard` being a
separate IAM action and on the card living beneath `/invocations/`, both of
which are AgentCore-specific and cost time to meet the hard way. It also states
plainly that the AgentCore card publishes the agent's full system prompt and
model id, which is the thing an AWS reader most needs to know before shipping.

Post to an organization by passing `organization_id` in the article payload.
AWS Community Builders is `2794`; the id is at
`https://dev.to/api/organizations/<slug>`.

## Posting to AWS Builder Center

`builder.aws.com` has no import and no API. The body is a rich text editor, but
it **parses markdown on paste**, so the whole article can go in as one paste
rather than being retyped. Headings, tables, inline code and fenced code blocks
all convert, and a fenced block becomes an editable code widget with syntax
highlighting.

Four behaviours, measured 2026-08-26:

- **Paste the whole body in one go.** A heading at the start of a second paste
  is merged into the trailing paragraph of the first and arrives as plain text,
  not a heading. It happens silently and only shows up in a heading count.
- **The editor ignores programmatic edits.** `execCommand('delete')`, DOM
  removal and synthetic selections do not stick; only real key events do. Fixing
  the merged heading needed a click, `shift+End`, `Delete`, `Return`, then
  typing `## ` and the title, which the editor's markdown shortcut converts.
- **A stray click inside a code block opens its editor modal**, and a
  `ctrl+a` after that clears the modal rather than the document. Position the
  caret through the DOM and only use real keys for the edit itself.
- **CSP blocks outbound `fetch` and `XMLHttpRequest`**, so the page cannot pull
  its own markdown from raw.githubusercontent. The content has to be embedded in
  the injected script.

### What its publish validator rejects

Builder Center runs a validator before it will publish. It reported four broken
links, one malicious link and profanity on the first attempt, none of which name
the offending text. What each turned out to be, measured 2026-08-26:

- **Broken links** were every bare URL in the prose that does not resolve on its
  own: `https://bedrock-agentcore.us-west-2.amazonaws.com` as a bare host, and
  the truncated `https://bedrock-agentcore...` used as a placeholder in the
  quoted card. The validator reads URLs out of the text, not just out of
  anchors, so a URL inside a code block counts too.
- **Malicious link** was `http://0.0.0.0:8080`. Writing the bind address with a
  scheme makes it a URL, and `0.0.0.0` is on the address blocklists URL scanners
  use. Written as `0.0.0.0:8080` it is prose and passes.
- **Profanity** was a substring match. The article contained `analysis` in a
  quoted tag list and `assistant` in a quoted system prompt. Both are the
  classic Scunthorpe false positives, `anal` and `ass`. Neither word was needed:
  the tag list was illustrative, and the prompt is better shown as
  `<the full system prompt, 1,258 chars>` anyway.

The fix for all of it is to keep placeholder URLs out of prose and code, and to
write example addresses without a scheme. After it, the body contained one real
link and the validator passed.

The description also draws an SEO warning above 160 characters, separately from
its own 512 limit.

Count headings and tables after pasting. Both are cheap to check and both catch
the merge.

## Posting to dev.to

The dev.to API takes the markdown directly, so no image rendering is involved:

```bash
curl -X POST https://dev.to/api/articles \
  -H "api-key: $(cat ~/.devto.key)" -H "Content-Type: application/json" \
  --data-binary @article.json
```

**Send a real User-Agent.** Measured 2026-08-26: the identical payload returned
a bodyless `403` from `urllib` and `201` from `curl`. It is not permissions,
payload shape or content -- `Python-urllib/3.13` is refused by User-Agent.
Setting a browser User-Agent on the same `urllib` request makes it work, which
is what `post_devto.py` does. The `403` carries no body and no `cf-*` headers,
so nothing in the response says what was rejected.

**Unwrap prose before posting.** Forem parses markdown with hard wrap enabled,
so a single newline becomes a `<br>`. Prose hard wrapped at 80 columns arrives
with a line break after every source line, and the article reads ragged down the
page. The markdown here stays wrapped because that is what makes diffs
readable, so `post_devto.py` joins each paragraph into one line on the way out
and leaves fences, tables, headings and list items alone:

```bash
python3 docs/post_devto.py devto-aws-draft.md --id 4489111
```

Measured after the fix: zero paragraphs with a mid-paragraph break in either
article. The breaks that remain are one per paragraph immediately preceding a
code fence, which Forem adds itself and which renders as slightly more space.

## Image URLs

Image references in `medium-draft.md` are absolute
`raw.githubusercontent.com` URLs, because a relative path resolves to nothing
once the markdown leaves the repo. The images must be pushed and public before
an import will fetch them.

## The numbers in the images

`make_medium.py` parses the tables and code blocks out of `devto-draft.md`
rather than restating them. An image is the one place in this repo where a stale
number cannot be caught by grep, so the generator reads the article that carries
the numbers instead of holding a second copy of them.
