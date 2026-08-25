#!/usr/bin/env python3
"""Build the Medium version of the article from the dev.to version.

Medium renders no markdown tables at all, and its importer flattens every
multi-line code block onto one line. So the Medium version carries the same
prose with every table and every multi-line code block rendered as a PNG.

    uv pip install --system matplotlib
    python3 docs/make_medium.py

Reads ``docs/devto-draft.md``. Writes ``docs/medium-draft.md`` and the images
under ``docs/img/medium/``.

**The tables and code are parsed out of the dev.to source, not restated here.**
An image is the one place in a repo where a stale number cannot be caught by
grep. Reading the numbers from the article that carries them means the two can
never disagree; the alternative is a second copy of every figure maintained by
hand.

Three importer behaviours shape the output, each measured on 2026-08-23 and
recorded in the predecessor repo's ``docs/MEDIUM-PUBLISHING.md``:

- ``<pre>`` is flattened to one line and ``<br>`` is stripped, so multi-line
  code cannot survive as text. Single-line blocks are left inline; there is
  nothing in a one-line ``curl`` to flatten.
- Markdown tables do not render.
- Medium has two heading sizes. ``#`` and ``##`` both become the large one, so
  section headings are emitted as ``####`` or a twelve-section article reads as
  twelve titles.
"""

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Shell examples are full of `$` and field names are full of `_`. Without this,
# matplotlib reads the first `$` as the start of a mathtext expression and
# raises on the whole block.
matplotlib.rcParams["text.parse_math"] = False

DOCS = Path(__file__).parent
OUT = DOCS / "img" / "medium"

# Absolute, because a relative path resolves to nothing once the markdown is
# pasted into Medium or handed to the importer. Raw GitHub serves these
# directly and Medium rehosts whatever it fetches.
RAW = "https://raw.githubusercontent.com/xbill9/multicloud-agentcard/master/docs"
OUT.mkdir(parents=True, exist_ok=True)

# Light surface deliberately. Medium serves one image to both its themes, and
# text drawn for one theme is illegible in the other. A light card on a dark
# page is the failure mode every reader already accepts.
SURFACE = "#ffffff"
INK = "#101413"
INK_2 = "#4a5754"
RULE = "#dfe3dd"
HEAD_BG = "#eef1ec"
ACCENT = "#1e6b58"
CODE_BG = "#f7f8f6"

DPI = 150
WIDTH_IN = 10.0  # 1500px at 150dpi

MONO = ["DejaVu Sans Mono", "monospace"]
SANS = ["DejaVu Sans", "sans-serif"]


def parse_blocks(text: str):
    """Yield ('table'|'code'|'text', payload) in document order."""
    lines = text.split("\n")
    i, out, buf = 0, [], []

    def flush():
        if buf:
            out.append(("text", "\n".join(buf)))
            buf.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            fence = [line]
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                fence.append(lines[i])
                i += 1
            fence.append("```")
            i += 1
            flush()
            out.append(("code", "\n".join(fence)))
            continue
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
            tbl = []
            while i < len(lines) and lines[i].startswith("|"):
                tbl.append(lines[i])
                i += 1
            flush()
            out.append(("table", "\n".join(tbl)))
            continue
        buf.append(line)
        i += 1
    flush()
    return out


def table_rows(md: str):
    rows = [r.strip() for r in md.strip().split("\n")]
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    return cells[0], cells[2:]  # header, body (row 1 is the ---- separator)


def render_table(header, body, path: Path):
    ncol = len(header)
    nrow = len(body)
    # Column widths from the longest cell, so wide prose columns get room.
    widths = [
        max(len(header[c]), *(len(r[c]) if c < len(r) else 0 for r in body)) or 1
        for c in range(ncol)
    ]
    total = sum(widths)
    fracs = [w / total for w in widths]

    row_h = 0.34
    fig_h = row_h * (nrow + 1) + 0.35
    fig, ax = plt.subplots(figsize=(WIDTH_IN, fig_h), dpi=DPI)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, nrow + 1)
    ax.axis("off")
    fig.patch.set_facecolor(SURFACE)

    # header band
    ax.add_patch(plt.Rectangle((0, nrow), 1, 1, color=HEAD_BG, zorder=0))

    def xs():
        x, acc = [], 0.0
        for f in fracs:
            x.append(acc)
            acc += f
        return x

    xpos = xs()
    pad = 0.006
    fs = 9.5 if ncol > 4 else 10.5

    for c, name in enumerate(header):
        ax.text(xpos[c] + pad, nrow + 0.5, name, va="center", ha="left",
                fontsize=fs, color=INK_2, family=SANS, weight="bold")

    for r, row in enumerate(body):
        y = nrow - r - 0.5
        ax.plot([0, 1], [y + 0.5, y + 0.5], color=RULE, lw=0.7, zorder=1)
        for c in range(ncol):
            val = row[c] if c < len(row) else ""
            mono = bool(re.fullmatch(r"[`\w\-./:+*\[\]{}()<>|%,\s]*", val)) and "`" in val
            val = val.replace("`", "").replace("**", "")
            color = INK
            if val in ("no", "absent", "FAILED", "error"):
                color = "#a63239"
            elif val in ("yes", "confirmed", "identical", "works"):
                color = ACCENT
            ax.text(xpos[c] + pad, y, val, va="center", ha="left", fontsize=fs,
                    color=color, family=MONO if mono else SANS)

    ax.plot([0, 1], [nrow, nrow], color=INK, lw=1.1, zorder=2)
    fig.tight_layout(pad=0.3)
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def render_code(code: str, path: Path):
    body = "\n".join(code.split("\n")[1:-1])
    lines = body.split("\n")
    fig_h = max(0.5, 0.185 * len(lines) + 0.3)
    fig, ax = plt.subplots(figsize=(WIDTH_IN, fig_h), dpi=DPI)
    ax.axis("off")
    fig.patch.set_facecolor(CODE_BG)
    ax.text(0.012, 0.97, body, va="top", ha="left", fontsize=9.6,
            family=MONO, color=INK, linespacing=1.42,
            transform=ax.transAxes)
    fig.savefig(path, facecolor=CODE_BG, bbox_inches="tight")
    plt.close(fig)


def alt_safe(text: str) -> str:
    """Make a snippet safe to sit inside markdown image alt text.

    Brackets and parentheses in alt text break ``![alt](url)``. A code line such
    as ``05bb15448c63 -> ['research_agent',`` carries an unbalanced ``[``, and
    python-markdown then leaves the whole reference as literal text rather than
    emitting an image. Measured 2026-08-25: exactly one figure of thirty-two
    went missing this way, and it is invisible in the markdown.
    """
    return re.sub(r"[\[\]()]", "", text).strip()


def main() -> None:
    src = (DOCS / "devto-draft.md").read_text()
    # drop the dev.to front matter
    if src.startswith("---"):
        src = src.split("---", 2)[2].lstrip("\n")

    blocks = parse_blocks(src)
    out_md, n_tbl, n_code = [], 0, 0

    for kind, payload in blocks:
        if kind == "table":
            n_tbl += 1
            header, body = table_rows(payload)
            name = f"table-{n_tbl:02d}.png"
            render_table(header, body, OUT / name)
            # Caption is plain text. A link inside a figcaption makes Medium
            # drop the entire figure, silently.
            alt = alt_safe("Table: " + "; ".join(header))
            out_md.append(f"![{alt}]({RAW}/img/medium/{name})")
        elif kind == "code":
            inner = payload.split("\n")[1:-1]
            if len(inner) <= 1:
                out_md.append(payload)  # nothing to flatten in a one-liner
            else:
                n_code += 1
                name = f"code-{n_code:02d}.png"
                render_code(payload, OUT / name)
                first = next((ln for ln in inner if ln.strip()), "")
                out_md.append(f"![{alt_safe('Code: ' + first)[:70]}]({RAW}/img/medium/{name})")
        else:
            # Medium has two heading sizes. Push every section heading down to
            # the small one, or the article reads as a stack of titles.
            text = re.sub(r"^## ", "#### ", payload, flags=re.MULTILINE)
            out_md.append(text)

    header_img = ("![Three agent cards compared side by side. The Cloud Run card on the "
                  "left is sparse, the AgentCore card in the centre is four times denser, "
                  "and the Container Apps card on the right is dimmed behind a lock "
                  "because it returns 401.](" + RAW + "/article-header.jpg)")
    md = ("# Cross Cloud A2A Agent Card Field Comparison\n\n"
          + header_img + "\n\n" + "\n\n".join(b.strip("\n") for b in out_md if b.strip()) + "\n")
    (DOCS / "medium-draft.md").write_text(md)
    print(f"medium-draft.md written: {n_tbl} tables and {n_code} code blocks as images")


if __name__ == "__main__":
    main()
