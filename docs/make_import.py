#!/usr/bin/env python3
"""Render the Medium draft as an HTML page the Medium importer can fetch.

    python3 docs/make_import.py

Writes ``docs/import/<slug>-<sha10>.html`` and prints the import URL. Push it,
wait for Pages to serve it, then paste that URL into ``medium.com/p/import``.
It arrives as a draft.

Three things about the output, each of which cost a wasted import in the
predecessor repo and are recorded in ``docs/PUBLISHING.md``:

- **The filename is content addressed.** Medium's importer caches by URL *and
  ignores the query string*, so ``?v=2`` does not defeat it. A name derived
  from the content hash is a URL Medium has never seen, so there is nothing to
  serve stale.
- **No ``<link rel="canonical">``.** The importer resolves it and serves that
  URL's cached copy instead of the page actually submitted.
- **No link inside any ``<figcaption>``.** A caption containing an ``<a>``
  makes Medium drop the entire figure, silently and with no placeholder.

Images are absolute URLs against the Pages site. An importer rebuilding the
page elsewhere has nothing to resolve a relative path against.
"""

import hashlib
import re
from pathlib import Path

import markdown

DOCS = Path(__file__).parent
OUT = DOCS / "import"
SITE = "https://xbill9.github.io/multicloud-agentcard"
SLUG = "agent-card-field-comparison"

# Deliberately plain. The importer keeps the structure and discards the styling,
# so anything beyond readable defaults is spent on a page nobody reads twice.
STYLE = """
body { max-width: 46rem; margin: 2rem auto; padding: 0 1rem;
       font: 17px/1.6 Georgia, 'Times New Roman', serif; color: #1a1a1a; }
h1 { font-size: 2.1rem; line-height: 1.15; }
h4 { font-size: 1.25rem; margin-top: 2.2rem; }
img { max-width: 100%; height: auto; display: block; margin: 1.4rem 0; }
figure { margin: 1.6rem 0; }
figcaption { font-size: 0.85rem; color: #666; }
pre, code { font-family: ui-monospace, 'SF Mono', Menlo, monospace; font-size: 0.9em; }
pre { background: #f6f7f4; padding: 0.8rem 1rem; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
td, th { border-bottom: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; }
"""


def build() -> Path:
    md = (DOCS / "medium-draft.md").read_text()

    # Point the images at the Pages site rather than raw.githubusercontent, so
    # every image is same-origin with the page the importer is reading. The
    # markdown keeps the raw.githubusercontent URLs, which survive Pages being
    # turned off; the importer gets the copy it is most likely to follow.
    md = md.replace(
        "https://raw.githubusercontent.com/xbill9/multicloud-agentcard/master/docs",
        SITE,
    )

    html_body = markdown.markdown(md, extensions=["tables", "fenced_code"])

    # Replace the whole enclosing paragraph, not just the img inside it.
    # python-markdown wraps a standalone image line in <p>, and <figure> is not
    # allowed inside <p>: a parser closes the paragraph at the figure's start
    # tag, and Medium's importer discards what that leaves. Measured
    # 2026-08-25 -- two imports arrived with the prose intact and all 31
    # figures missing, from <p><figure>...</figure></p>.
    # Medium takes figcaption as the caption; a link in one drops the figure.
    def figure(m):
        alt, src = m.group(1), m.group(2)
        caption = re.sub(r"<[^>]+>", "", alt)
        return (f'<figure><img src="{src}" alt="{alt}" />'
                f"<figcaption>{caption}</figcaption></figure>")

    html_body = re.sub(
        r'<p>\s*<img alt="([^"]*)" src="([^"]*)"\s*/?>\s*</p>', figure, html_body
    )

    page = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Cross Cloud A2A Agent Card Field Comparison</title>\n"
        f"<style>{STYLE}</style>\n"
        "</head>\n<body>\n"
        f"{html_body}\n"
        "</body>\n</html>\n"
    )

    digest = hashlib.sha256(page.encode()).hexdigest()[:10]
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob(f"{SLUG}-*.html"):
        stale.unlink()
    path = OUT / f"{SLUG}-{digest}.html"
    path.write_text(page)
    return path


if __name__ == "__main__":
    p = build()
    print(f"wrote {p}")
    print(f"import URL: {SITE}/import/{p.name}")
