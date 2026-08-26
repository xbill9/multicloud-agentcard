#!/usr/bin/env python3
"""Post a draft to dev.to, with prose unwrapped for Forem's renderer.

    python3 docs/post_devto.py devto-aws-draft.md --id 4489111
    python3 docs/post_devto.py devto-draft.md --id 4488989

**Forem renders a single newline as a line break.** Its markdown is parsed with
hard wrap enabled, so a paragraph hard wrapped at 80 columns arrives with a
``<br>`` after every source line and the text reads ragged down the page. The
markdown in this repo stays wrapped, because that is what makes diffs readable;
this script joins each prose paragraph into one line on the way out.

What must *not* be joined is everything whose line structure carries meaning:
fenced code, tables, headings, list items and blockquotes. A list item wrapped
across lines is rejoined to its bullet, because the continuation is prose.

Also note the API refuses ``Python-urllib`` by User-Agent and answers a bodyless
403, so the request goes out with a browser User-Agent. See docs/PUBLISHING.md.
"""

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

DOCS = Path(__file__).parent
API = "https://dev.to/api/articles"
UA = "Mozilla/5.0 (X11; Linux x86_64) multicloud-agentcard/1.0"

#: Lines whose own structure matters and which therefore never join upward.
BLOCK_START = re.compile(r"^\s*(#{1,6} |[-*+] |\d+\. |> |\||!\[|```)")


def unwrap(md: str) -> str:
    """Join hard wrapped prose into one line per paragraph."""
    out: list[str] = []
    para: list[str] = []
    in_fence = False

    def flush() -> None:
        if para:
            out.append(" ".join(x.strip() for x in para))
            para.clear()

    for line in md.split("\n"):
        if line.lstrip().startswith("```"):
            flush()
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if not line.strip():
            flush()
            out.append("")
            continue
        if BLOCK_START.match(line):
            # A list item continues onto the next line in this repo's wrapping,
            # so keep collecting into it rather than starting a fresh block.
            flush()
            if re.match(r"^\s*([-*+] |\d+\. )", line):
                para.append(line)
            else:
                out.append(line)
            continue
        if para:
            para.append(line)
        else:
            para.append(line)
    flush()
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--id", required=True, help="dev.to article id to update")
    args = ap.parse_args()

    raw = (DOCS / args.draft).read_text()
    body = unwrap(raw.split("---", 2)[2].lstrip("\n"))

    key = Path.home().joinpath(".devto.key").read_text().strip()
    req = urllib.request.Request(
        f"{API}/{args.id}",
        data=json.dumps({"article": {"body_markdown": body}}).encode(),
        headers={"api-key": key, "Content-Type": "application/json", "User-Agent": UA},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.load(r)
        print(f"  updated {out['id']}: {out.get('url')}")
    except urllib.error.HTTPError as exc:
        print(f"  HTTP {exc.code}: {exc.read().decode()[:300]}")


if __name__ == "__main__":
    main()
