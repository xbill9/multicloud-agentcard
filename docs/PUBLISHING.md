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
