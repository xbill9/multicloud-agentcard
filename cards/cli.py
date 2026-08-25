"""Pull agent cards from remote native agents and read what came back.

    agentcard fetch                          # the three deployed legs
    agentcard fetch --peer demo=https://x/   # anything else, no code change
    agentcard fetch --markdown report.md --save
    agentcard show gcp                       # one card, raw, from the last run
    agentcard replay --markdown report.md    # re-review a stored run, no network
    agentcard diff                           # what changed since the run before
    agentcard history

``fetch`` is the only subcommand that touches the network. Everything else
works over the stored corpus, which is deliberate: the reviewing and comparing
is where the iteration happens, and iterating on it should not mean dialling
three clouds each time -- nor should it be possible to accidentally change what
a past run "found" by re-fetching it.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from cards import compare as compare_mod
from cards import report as report_mod
from cards import store
from cards.fetch import CARD_PATHS, fetch_all
from cards.model import Corpus
from cards.review import ERROR, review_all
from peers.errors import AdapterError
from peers.registry import (
    BUILTIN_PEERS,
    DEFAULT_TIMEOUT_SECONDS,
    build_peers,
    builtin_specs,
    load_specs,
    parse_inline,
)

#: Exit 3 when every peer refused to serve a card. Distinct from 1, which is a
#: bad invocation, and from 2, which is a defect found. A caller scripting this
#: -- a control harness, CI -- has to be able to tell "the instrument failed"
#: from "the instrument worked and the news is bad".
NO_CARDS_EXIT = 3
DEFECTS_EXIT = 2

#: Exit 4 when a card changed since the run before. Separate from 2 because a
#: defect and a change are opposite kinds of news: a defect is a card that is
#: wrong *now*, drift is a card that is different from the one this project
#: last read -- and a vendor moving 0.3 -> 1.0 between two deploys, with every
#: check still green, is the event `CLAUDE.md` says this repo exists to catch.
#: Gating on defects alone would let exactly that through.
DRIFT_EXIT = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentcard",
        description="Fetch A2A agent cards from remote native agents and compare them",
    )
    parser.add_argument(
        "--corpus-dir",
        default=str(store.DEFAULT_DIR),
        help=f"where stored runs live (default {store.DEFAULT_DIR}, $CARD_CORPUS_DIR)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log every round trip")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="dial every peer and review what comes back")
    fetch.add_argument(
        "--peer",
        action="append",
        default=[],
        metavar="NAME=URL[,auth=MODE][,runtime=TEXT]",
        help="an extra peer, repeatable; suppresses the built-in three unless "
        "--builtin is also given",
    )
    fetch.add_argument(
        "--peers-file",
        help="TOML file of [[peer]] entries; same suppression rule as --peer",
    )
    fetch.add_argument(
        "--builtin",
        action="append",
        choices=list(BUILTIN_PEERS),
        help="a built-in peer to include, repeatable; default is all three when "
        "no --peer or --peers-file is given",
    )
    fetch.add_argument(
        "--path",
        action="append",
        default=[],
        help=f"discovery path to try, repeatable; default {' then '.join(CARD_PATHS)}",
    )
    fetch.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    fetch.add_argument("--markdown", metavar="FILE", help="write the full report here")
    fetch.add_argument("--json", metavar="FILE", help="write the whole run as JSON here")
    fetch.add_argument("--save", action="store_true", help="store the corpus for later")
    fetch.add_argument(
        "--fail-on-defect",
        action="store_true",
        help=f"exit {DEFECTS_EXIT} if any card has an error-severity finding",
    )
    fetch.add_argument(
        "--fail-on-change",
        action="store_true",
        help=f"exit {DRIFT_EXIT} if any card differs from the previous stored run",
    )

    replay = sub.add_parser("replay", help="re-review a stored run, no network")
    replay.add_argument("run", nargs="?", help="path to a stored run; default the latest")
    replay.add_argument("--markdown", metavar="FILE")
    replay.add_argument("--json", metavar="FILE")

    show = sub.add_parser("show", help="print one peer's card exactly as it arrived")
    show.add_argument("peer")
    show.add_argument("run", nargs="?", help="path to a stored run; default the latest")
    show.add_argument(
        "--raw",
        action="store_true",
        help="the bytes as served, not re-indented -- key order and escaping intact",
    )

    diff = sub.add_parser("diff", help="what changed between two stored runs")
    diff.add_argument("old", nargs="?", help="default: the run before the latest")
    diff.add_argument("new", nargs="?", help="default: the latest")
    diff.add_argument(
        "--fail-on-change",
        action="store_true",
        help=f"exit {DRIFT_EXIT} if any card changed",
    )

    sub.add_parser("history", help="list stored runs")
    return parser


def _specs(args):
    inline = parse_inline(args.peer) if args.peer else []
    from_file = load_specs(args.peers_file) if args.peers_file else []
    # Built-ins come in when nothing else was named, or when asked for
    # explicitly. Silently adding all three to an explicit `--peer` list would
    # make a run against one public agent dial two clouds it was not asked
    # about, which at best wastes a credential mint and at worst reports a
    # denial for a peer nobody mentioned.
    if args.builtin:
        builtin = builtin_specs(args.builtin)
    elif not inline and not from_file:
        builtin = builtin_specs()
    else:
        builtin = []
    return [*builtin, *from_file, *inline]


def _render(corpus: Corpus, args) -> tuple[int, list]:
    reviews = review_all(corpus.specimens)
    comparison = compare_mod.compare(reviews)
    costs = compare_mod.fetch_costs(corpus)

    print(report_mod.terminal(corpus, reviews, comparison, costs))

    if getattr(args, "markdown", None):
        text = report_mod.markdown(corpus, reviews, comparison, costs)
        Path(args.markdown).write_text(text)
        print(f"\nwrote {args.markdown} ({len(text)} bytes)")
    if getattr(args, "json", None):
        text = store.as_json(corpus, reviews, comparison, costs)
        Path(args.json).write_text(text)
        print(f"wrote {args.json} ({len(text)} bytes)")

    errors = sum(1 for r in reviews for f in r.findings if f.severity == ERROR)
    return errors, reviews


def _latest_or_exit(directory: Path) -> Corpus:
    corpus = store.latest(directory)
    if corpus is None:
        print(
            f"no stored runs in {directory}. Run `agentcard fetch --save` first.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return corpus


def _report_drift(previous: Corpus | None, current: Corpus) -> bool:
    """Print what changed since the previous run. True if anything did.

    Printed unconditionally, gated only on request. A run whose cards moved is
    worth saying so about even when nobody asked the process to fail -- the
    whole reason the corpus is dated is that "did this card change" is the
    question, and answering it only under a flag means the usual run never asks.
    """
    if previous is None:
        return False
    changes = store.diff_specimens(previous, current)
    if not changes:
        return False
    print(f"\ndrift since {previous.run_id}:")
    for peer, entries in changes.items():
        print(f"  {peer}:")
        for entry in entries:
            print(f"    {entry}")
    return True


def _load_or_exit(ref: str, directory: Path) -> Corpus:
    """Load a run the user named, reporting a miss in one line, not a traceback."""
    try:
        return store.load(store.resolve(ref, directory))
    except store.UnknownRun as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        format="[%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO if args.verbose else logging.WARNING,
    )
    directory = Path(args.corpus_dir)

    if args.command == "history":
        print(store.summarise(directory))
        return 0

    if args.command == "show":
        corpus = _load_or_exit(args.run, directory) if args.run else _latest_or_exit(directory)
        found = next((s for s in corpus.specimens if s.peer == args.peer), None)
        if found is None:
            print(
                f"no peer {args.peer!r} in that run "
                f"(have: {', '.join(s.peer for s in corpus.specimens)})",
                file=sys.stderr,
            )
            return 1
        if not found.raw:
            print(f"{args.peer} served no body: {found.error}", file=sys.stderr)
            return NO_CARDS_EXIT
        print(found.raw if args.raw else found.pretty())
        return 0

    if args.command == "diff":
        runs = store.history(directory)
        if args.old and args.new:
            old = _load_or_exit(args.old, directory)
            new = _load_or_exit(args.new, directory)
        elif len(runs) < 2:
            print("need two stored runs to diff", file=sys.stderr)
            return 1
        else:
            old, new = store.load(runs[-2]), store.load(runs[-1])
        changes = store.diff_specimens(old, new)
        if not changes:
            print(f"no card changed between {old.run_id} and {new.run_id}")
            return 0
        print(f"{old.run_id} -> {new.run_id}")
        for peer, entries in changes.items():
            print(f"  {peer}:")
            for entry in entries:
                print(f"    {entry}")
        return DRIFT_EXIT if args.fail_on_change else 0

    if args.command == "replay":
        corpus = _load_or_exit(args.run, directory) if args.run else _latest_or_exit(directory)
        _render(corpus, args)
        return 0

    # fetch
    try:
        peers = build_peers(_specs(args))
    except (AdapterError, ValueError) as exc:
        # The provider's own words, at the boundary, before anything is dialled.
        # A credential that cannot be minted must fail here and say why -- not
        # halfway through a fan-out where it is indistinguishable from the
        # remote being down.
        print(f"cannot assemble the peer list: {exc}", file=sys.stderr)
        return 1

    print(
        f"fetching {len(peers)} card(s): "
        + ", ".join(f"{p.name} ({p.resolved_auth})" for p in peers),
        file=sys.stderr,
    )
    paths = tuple(args.path) if args.path else CARD_PATHS
    # Read before the fetch is stored, not after: `--save` writes this run into
    # the same directory, and a `latest` taken afterwards is the run we just
    # made -- which diffs clean against itself and reports drift never happens.
    previous = store.latest(directory)

    corpus = asyncio.run(
        fetch_all(peers, timeout_seconds=args.timeout, paths=paths)
    )

    if args.save:
        path = store.save(corpus, directory)
        print(f"stored {path}", file=sys.stderr)

    errors, _ = _render(corpus, args)
    drifted = _report_drift(previous, corpus)

    if not corpus.fetched:
        return NO_CARDS_EXIT
    if args.fail_on_defect and errors:
        return DEFECTS_EXIT
    if args.fail_on_change and drifted:
        return DRIFT_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
