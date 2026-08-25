"""Keep the specimens, so a comparison can be re-run without dialling anything.

Two reasons, and the second is the one that matters.

A stored corpus makes ``review`` and ``compare`` **testable against reality**:
every check in this repo can be exercised over cards three real runtimes
actually served, instead of over cards this repo made up about them.

And a corpus is dated. The interesting question about a vendor's card is not
what it says today, it is what changed -- and a runtime that quietly moves from
0.3 to 1.0 between two deploys is exactly the event this repo exists to catch.
That is only visible against a copy of the old one.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from cards.model import Corpus

DEFAULT_DIR = Path(os.getenv("CARD_CORPUS_DIR", ".cards"))


def save(corpus: Corpus, directory: Path | str = DEFAULT_DIR) -> Path:
    """Write one run to ``<dir>/<timestamp>-<run_id>.json``.

    Timestamp first so the directory sorts chronologically in a plain ``ls``,
    run id after so two runs in the same second cannot collide.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = corpus.started_at.strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}-{corpus.run_id}.json"
    path.write_text(corpus.model_dump_json(indent=2))
    return path


def load(path: Path | str) -> Corpus:
    return Corpus.model_validate_json(Path(path).read_text())


def history(directory: Path | str = DEFAULT_DIR) -> list[Path]:
    """Every stored run, oldest first."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def latest(directory: Path | str = DEFAULT_DIR) -> Corpus | None:
    runs = history(directory)
    return load(runs[-1]) if runs else None


def diff_specimens(old: Corpus, new: Corpus) -> dict[str, list[str]]:
    """What changed per peer between two runs, at the level of card keys.

    Deliberately shallow. A deep structural diff of two cards is a solved
    problem and a bad report: it buries "this runtime moved to 1.0" under
    forty reordered skill tags. Key presence and a raw-body checksum answer
    "did this card change, and roughly where" -- and the stored bodies are
    right there when the answer is yes.
    """
    before = {s.peer: s for s in old.specimens}
    changes: dict[str, list[str]] = {}
    for specimen in new.specimens:
        was = before.get(specimen.peer)
        entries: list[str] = []
        if was is None:
            changes[specimen.peer] = ["new peer in this run"]
            continue
        if was.raw == specimen.raw:
            continue
        if was.card is None and specimen.card is not None:
            entries.append("card now retrievable (it was not before)")
        elif was.card is not None and specimen.card is None:
            entries.append(f"card no longer retrievable: {specimen.error}")
        if was.card and specimen.card:
            gone = sorted(set(was.card) - set(specimen.card))
            added = sorted(set(specimen.card) - set(was.card))
            if added:
                entries.append(f"fields added: {', '.join(added)}")
            if gone:
                entries.append(f"fields removed: {', '.join(gone)}")
            for key in sorted(set(was.card) & set(specimen.card)):
                if was.card[key] != specimen.card[key]:
                    entries.append(f"{key} changed")
        if not entries:
            entries.append("body changed with no change to any key")
        changes[specimen.peer] = entries
    return changes


def _stamp(value: datetime) -> str:  # pragma: no cover - trivial
    return value.strftime("%Y-%m-%d %H:%M:%SZ")


def summarise(directory: Path | str = DEFAULT_DIR) -> str:
    runs = history(directory)
    if not runs:
        return "no stored runs"
    lines = []
    for path in runs:
        corpus = load(path)
        lines.append(
            f"{_stamp(corpus.started_at)}  {corpus.run_id}  "
            f"{len(corpus.fetched)}/{len(corpus.specimens)} card(s)  {path.name}"
        )
    return "\n".join(lines)


def as_json(corpus: Corpus, reviews, comparison, costs) -> str:
    """The whole run as one JSON document, for anything downstream."""
    return json.dumps(
        {
            "run_id": corpus.run_id,
            "started_at": corpus.started_at.isoformat(),
            "elapsed_ms": round(corpus.elapsed_ms, 1),
            "peers": [s.peer for s in corpus.specimens],
            "specimens": [json.loads(s.model_dump_json()) for s in corpus.specimens],
            "reviews": [
                {
                    "peer": r.peer,
                    "shape": r.shape.label if r.shape else "",
                    "declared_version": r.shape.declared if r.shape else "",
                    "facts": r.facts,
                    "findings": [
                        {
                            "severity": f.severity,
                            "code": f.code,
                            "title": f.title,
                            "detail": f.detail,
                            "field": f.field,
                        }
                        for f in r.findings
                    ],
                }
                for r in reviews
            ],
            "comparison": {
                "peers": comparison.peers,
                "axes": [
                    {
                        "key": a.key,
                        "label": a.label,
                        "values": a.values,
                        "agree": a.agree,
                        "consequence": a.consequence,
                    }
                    for a in comparison.axes
                ],
                "field_presence": comparison.field_presence,
                "universal_fields": comparison.universal_fields,
                "unique_fields": comparison.unique_fields,
            },
            "fetch_costs": [
                {
                    "peer": c.peer,
                    "auth": c.auth,
                    "keyless": c.keyless,
                    "round_trips": c.round_trips,
                    "credential_ms": round(c.credential_ms, 1),
                    "discovery_ms": round(c.discovery_ms, 1),
                    "total_ms": round(c.total_ms, 1),
                    "paths_tried": c.paths_tried,
                    "path": c.path,
                    "request_id": c.request_id,
                }
                for c in costs
            ],
        },
        indent=2,
    )
