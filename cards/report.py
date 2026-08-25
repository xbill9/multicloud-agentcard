"""Render a run: markdown for reading, a table for the terminal.

One renderer, not two half-renderers. The markdown *is* the report and the
terminal output is the same document with the tables narrowed, because two
independent renderers drift and then the artifact somebody circulates says
something the run did not.

Ordering is fixed and is an argument, not a layout:

1. **what failed** -- a run with a denied peer is not a run with fewer peers
2. **the contrast** -- what the peers disagree about, which is the question
3. **per-card defects** -- errors and warnings, by peer
4. **the observations** -- notes, where most of the compare-and-contrast lives
5. **what it cost to ask** -- round trips, credential mints, request ids
"""

from cards.compare import Comparison, FetchCost
from cards.model import Corpus
from cards.review import ERROR, NOTE, WARNING, Review

_SEVERITY_MARK = {ERROR: "**error**", WARNING: "warning", NOTE: "note"}
_TERMINAL_MARK = {ERROR: "ERR ", WARNING: "WARN", NOTE: "note"}


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
        *("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows),
    ]


def _cell(value) -> str:
    """Pipes and newlines both end a markdown table row early."""
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def markdown(
    corpus: Corpus,
    reviews: list[Review],
    comparison: Comparison,
    costs: list[FetchCost],
) -> str:
    lines: list[str] = [
        f"# Agent cards, {len(corpus.specimens)} peer(s)",
        "",
        (f"Run `{corpus.run_id}` · {corpus.started_at.isoformat()} · "
        f"{corpus.elapsed_ms:.0f}ms wall clock · "
        f"{len(corpus.fetched)} card(s) retrieved, {len(corpus.failed)} not."),
        "",
    ]

    lines += _section_failures(corpus)
    lines += _section_overview(corpus, reviews)
    lines += _section_contrast(comparison)
    lines += _section_fields(comparison)
    lines += _section_defects(reviews)
    lines += _section_notes(reviews)
    lines += _section_cost(costs)
    return "\n".join(lines).rstrip() + "\n"


def _section_failures(corpus: Corpus) -> list[str]:
    failed = corpus.failed
    if not failed:
        return []
    lines = [
        "## Peers that served no card",
        "",
        ("A denied fetch is a result, not a gap. Read this before the tables "
        "below -- every one of them is computed over the peers that answered."),
        "",
    ]
    lines += _table(
        ["peer", "endpoint", "kind", "what the provider said"],
        [
            [
                s.peer,
                s.endpoint,
                s.failure_kind or "-",
                (s.error or s.parse_error or "-")[:300],
            ]
            for s in failed
        ],
    )
    return [*lines, ""]


def _section_overview(corpus: Corpus, reviews: list[Review]) -> list[str]:
    by_peer = {r.peer: r for r in reviews}
    rows = []
    for specimen in corpus.specimens:
        review = by_peer.get(specimen.peer)
        rows.append(
            [
                specimen.peer,
                specimen.runtime or "-",
                specimen.auth_used,
                specimen.path or "-",
                str(specimen.status or "-"),
                f"{specimen.byte_count}" if specimen.raw else "-",
                (review.shape.label if review and review.shape else "-"),
                str(len(review.errors)) if review else "-",
                str(len(review.warnings)) if review else "-",
            ]
        )
    return [
        "## What answered",
        "",
        *_table(
            ["peer", "runtime", "auth", "path", "status", "bytes", "shape", "err", "warn"],
            rows,
        ),
        "",
    ]


def _section_contrast(comparison: Comparison) -> list[str]:
    if len(comparison.peers) < 2:
        return [
            "## Contrast",
            "",
            ("Only one card was retrieved, so there is nothing to contrast. "
            "The per-card review below still applies."),
            "",
        ]
    lines = ["## Contrast", ""]

    divergences = comparison.divergences
    if divergences:
        lines += [
            f"**{len(divergences)} difference(s) a client has to handle.**",
            "",
        ]
        for axis in divergences:
            lines += [
                f"#### {axis.label}",
                "",
                *_table(
                    ["peer", "value"],
                    [[peer, axis.values.get(peer) or "-"] for peer in comparison.peers],
                ),
                "",
                f"*Consequence:* {axis.consequence}",
                "",
            ]
    else:
        lines += [
            "The peers agree on every axis with a client-visible consequence.",
            "",
        ]

    lines += ["#### Every axis, side by side", ""]
    lines += _table(
        ["axis", *comparison.peers, "agree"],
        [
            [
                axis.label,
                *[axis.values.get(peer) or "-" for peer in comparison.peers],
                "yes" if axis.agree else "no",
            ]
            for axis in comparison.axes
        ],
    )
    return [*lines, ""]


def _section_fields(comparison: Comparison) -> list[str]:
    if not comparison.field_presence or len(comparison.peers) < 2:
        return []
    lines = [
        "## Field presence",
        "",
        ("Which peers carry which top-level key. The rows that are not all "
        "ticks are where a client needs a fallback."),
        "",
    ]
    lines += _table(
        ["field", *comparison.peers],
        [
            [name, *["yes" if peer in peers else "-" for peer in comparison.peers]]
            for name, peers in comparison.field_presence.items()
        ],
    )
    if comparison.unique_fields:
        lines += [
            "",
            "Served by exactly one peer: "
            + ", ".join(
                f"`{field}` ({peer})"
                for field, peer in comparison.unique_fields.items()
            )
            + ".",
        ]
    return [*lines, ""]


def _section_defects(reviews: list[Review]) -> list[str]:
    defects = [(r, f) for r in reviews for f in r.findings if f.severity != NOTE]
    if not defects:
        return ["## Defects", "", "None. No errors and no warnings on any card.", ""]
    lines = ["## Defects", ""]
    for review in reviews:
        rows = [
            [_SEVERITY_MARK[f.severity], f.code, f.field or "-", f.title, f.detail]
            for f in review.findings
            if f.severity != NOTE
        ]
        if not rows:
            continue
        lines += [f"### {review.peer}", ""]
        lines += _table(["", "code", "field", "what", "why it matters"], rows)
        lines.append("")
    return lines


def _section_notes(reviews: list[Review]) -> list[str]:
    lines = [
        "## Observations",
        "",
        ("True statements with no defect attached. This is where most of the "
        "vendor-to-vendor difference actually lives."),
        "",
    ]
    for review in reviews:
        rows = [
            [f.code, f.field or "-", f.title, f.detail]
            for f in review.findings
            if f.severity == NOTE
        ]
        if not rows:
            continue
        lines += [f"### {review.peer}", ""]
        lines += _table(["code", "field", "what", "detail"], rows)
        lines.append("")
    return lines


def _section_cost(costs: list[FetchCost]) -> list[str]:
    if not costs:
        return []
    return [
        "## What discovery cost",
        "",
        ("Not on any card. A card fetched over a federated credential costs "
        "round trips to another cloud's identity provider first, and arrives "
        "byte-identical to one fetched from an open port."),
        "",
        *_table(
            [
                "peer",
                "auth",
                "keyless",
                "round trips",
                "credential ms",
                "discovery ms",
                "total ms",
                "paths tried",
                "provider request id",
            ],
            [
                [
                    c.peer,
                    c.auth,
                    "yes" if c.keyless else "no",
                    str(c.round_trips),
                    f"{c.credential_ms:.0f}",
                    f"{c.discovery_ms:.0f}",
                    f"{c.total_ms:.0f}",
                    str(c.paths_tried),
                    c.request_id or "-",
                ]
                for c in costs
            ],
        ),
        "",
    ]


def terminal(
    corpus: Corpus,
    reviews: list[Review],
    comparison: Comparison,
    costs: list[FetchCost],
) -> str:
    """The short form: what answered, what diverged, what is broken."""
    width = max((len(p) for p in [s.peer for s in corpus.specimens]), default=4)
    lines = [
        (f"run {corpus.run_id}  {len(corpus.fetched)}/{len(corpus.specimens)} card(s)"
        f"  {corpus.elapsed_ms:.0f}ms"),
        "",
    ]
    by_peer = {r.peer: r for r in reviews}
    for specimen in corpus.specimens:
        review = by_peer.get(specimen.peer)
        if not specimen.ok:
            lines.append(
                f"  {specimen.peer:<{width}}  FAILED  {specimen.failure_kind}: "
                f"{(specimen.error or '')[:90]}"
            )
            continue
        shape = review.shape.label if review and review.shape else "?"
        lines.append(
            f"  {specimen.peer:<{width}}  {specimen.status}  {shape:<8}"
            f"  {specimen.byte_count:>6}B  {specimen.auth_used:<16}"
            f"  {len(review.errors) if review else 0} err"
            f"  {len(review.warnings) if review else 0} warn"
        )

    divergences = comparison.divergences
    lines += ["", f"contrast: {len(divergences)} client-visible difference(s)"]
    for axis in divergences:
        lines.append(f"  {axis.label}:")
        for peer in comparison.peers:
            lines.append(f"    {peer:<{width}}  {axis.values.get(peer) or '-'}")

    defects = [f for r in reviews for f in r.findings if f.severity != NOTE]
    if defects:
        lines += ["", f"defects: {len(defects)}"]
        for finding in sorted(defects, key=lambda f: (f.rank, f.peer)):
            lines.append(
                f"  {_TERMINAL_MARK[finding.severity]} {finding.peer:<{width}}  "
                f"{finding.code}: {finding.title}"
            )
    else:
        lines += ["", "defects: none"]

    if costs:
        lines += ["", "discovery cost:"]
        for cost in costs:
            lines.append(
                f"  {cost.peer:<{width}}  {cost.round_trips} round trip(s)  "
                f"{cost.total_ms:.0f}ms  ({cost.auth})"
            )
    return "\n".join(lines)
