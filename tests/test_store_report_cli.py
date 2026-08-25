"""Storing a run, rendering it, and driving all of that from the command line."""

import json
from datetime import UTC, datetime

import pytest

from cards import store
from cards.cli import main
from cards.compare import compare, fetch_costs
from cards.model import Corpus, Specimen
from cards.report import markdown, terminal
from cards.review import review_all


def _corpus(*cards, run_id="r1") -> Corpus:
    return Corpus(
        run_id=run_id,
        started_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
        elapsed_ms=50,
        specimens=[
            Specimen(
                peer=name,
                endpoint=f"https://{name}.example",
                runtime="test",
                raw=json.dumps(card) if card else "",
                card=card,
                status=200 if card else 403,
                error="" if card else "403 on /.well-known/agent-card.json",
                failure_kind="" if card else "authentication",
            )
            for name, card in cards
        ],
    )


def _rendered(corpus):
    reviews = review_all(corpus.specimens)
    return corpus, reviews, compare(reviews), fetch_costs(corpus)


# --- store -----------------------------------------------------------------

def test_a_corpus_round_trips_through_disk(tmp_path, hybrid_card):
    path = store.save(_corpus(("aws", hybrid_card)), tmp_path)
    assert store.load(path).specimens[0].card == hybrid_card


def test_stored_runs_sort_chronologically(tmp_path, hybrid_card):
    for index in range(3):
        corpus = _corpus(("aws", hybrid_card), run_id=f"r{index}")
        corpus.started_at = datetime(2026, 8, 24, 12, index, tzinfo=UTC)
        store.save(corpus, tmp_path)
    assert [store.load(p).run_id for p in store.history(tmp_path)] == ["r0", "r1", "r2"]
    assert store.latest(tmp_path).run_id == "r2"


def test_latest_on_an_empty_directory_is_none(tmp_path):
    assert store.latest(tmp_path) is None
    assert store.history(tmp_path) == []


def test_diff_names_the_fields_that_changed(hybrid_card):
    after = {**hybrid_card, "iconUrl": "https://x/icon.png"}
    del after["documentationUrl"]
    after["version"] = "2.0.0"
    changes = store.diff_specimens(_corpus(("aws", hybrid_card)), _corpus(("aws", after)))
    entries = changes["aws"]
    assert any("fields added: iconUrl" in e for e in entries)
    assert any("fields removed: documentationUrl" in e for e in entries)
    assert any("version changed" in e for e in entries)


def test_diff_is_silent_when_nothing_changed(hybrid_card):
    assert store.diff_specimens(_corpus(("aws", hybrid_card)), _corpus(("aws", hybrid_card))) == {}


def test_diff_reports_a_card_becoming_unreachable(hybrid_card):
    changes = store.diff_specimens(_corpus(("aws", hybrid_card)), _corpus(("aws", None)))
    assert any("no longer retrievable" in e for e in changes["aws"])


# --- report ----------------------------------------------------------------

def test_markdown_leads_with_the_peers_that_served_nothing(hybrid_card):
    text = markdown(*_rendered(_corpus(("aws", hybrid_card), ("azure", None))))
    assert text.index("## Peers that served no card") < text.index("## Contrast")
    assert "403 on /.well-known/agent-card.json" in text


def test_markdown_has_no_failure_section_when_every_peer_answered(hybrid_card):
    text = markdown(*_rendered(_corpus(("aws", hybrid_card))))
    assert "## Peers that served no card" not in text


def test_a_pipe_in_a_card_cannot_break_the_table(hybrid_card, adk_card):
    """A vendor's skill id is not required to be markdown-safe.

    Two peers, because the contrast tables -- the ones that render card content
    verbatim -- only exist when there is something to contrast.
    """
    hybrid_card["skills"][0]["id"] = "a | b"
    text = markdown(*_rendered(_corpus(("aws", hybrid_card), ("gcp", adk_card))))
    assert "a \\| b" in text
    for line in text.splitlines():
        if line.startswith("|") and "---" not in line:
            assert line.endswith("|"), f"row ended early: {line}"


def test_a_single_card_says_there_is_nothing_to_contrast(hybrid_card):
    text = markdown(*_rendered(_corpus(("aws", hybrid_card))))
    assert "nothing to contrast" in text


def test_terminal_output_names_every_peer(hybrid_card, adk_card):
    text = terminal(*_rendered(_corpus(("aws", hybrid_card), ("gcp", adk_card), ("azure", None))))
    assert "aws" in text and "gcp" in text and "azure" in text
    assert "FAILED" in text


# --- cli -------------------------------------------------------------------

def test_replay_re_reviews_a_stored_run_without_a_network(tmp_path, hybrid_card, capsys):
    store.save(_corpus(("aws", hybrid_card)), tmp_path)
    assert main(["--corpus-dir", str(tmp_path), "replay"]) == 0
    assert "aws" in capsys.readouterr().out


def test_replay_writes_the_markdown_it_is_asked_for(tmp_path, hybrid_card):
    store.save(_corpus(("aws", hybrid_card)), tmp_path)
    out = tmp_path / "report.md"
    main(["--corpus-dir", str(tmp_path), "replay", "--markdown", str(out)])
    assert out.read_text().startswith("# Agent cards")


def test_show_prints_the_bytes_as_served(tmp_path, hybrid_card, capsys):
    corpus = _corpus(("aws", hybrid_card))
    corpus.specimens[0].raw = '{"name":"x"}'
    store.save(corpus, tmp_path)
    main(["--corpus-dir", str(tmp_path), "show", "aws", "--raw"])
    assert capsys.readouterr().out.strip() == '{"name":"x"}'


def test_show_of_an_unknown_peer_lists_what_the_run_had(tmp_path, hybrid_card, capsys):
    store.save(_corpus(("aws", hybrid_card)), tmp_path)
    assert main(["--corpus-dir", str(tmp_path), "show", "azure"]) == 1
    assert "aws" in capsys.readouterr().err


def test_history_on_an_empty_directory_is_not_an_error(tmp_path, capsys):
    assert main(["--corpus-dir", str(tmp_path), "history"]) == 0
    assert "no stored runs" in capsys.readouterr().out


def test_diff_needs_two_runs(tmp_path, hybrid_card, capsys):
    store.save(_corpus(("aws", hybrid_card)), tmp_path)
    assert main(["--corpus-dir", str(tmp_path), "diff"]) == 1
    assert "need two stored runs" in capsys.readouterr().err


def test_diff_of_two_stored_runs_reports_the_change(tmp_path, hybrid_card, capsys):
    first = _corpus(("aws", hybrid_card), run_id="r0")
    first.started_at = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    store.save(first, tmp_path)
    second = _corpus(("aws", {**hybrid_card, "version": "9"}), run_id="r1")
    second.started_at = datetime(2026, 8, 24, 12, 1, tzinfo=UTC)
    store.save(second, tmp_path)
    assert main(["--corpus-dir", str(tmp_path), "diff"]) == 0
    assert "version changed" in capsys.readouterr().out


def test_a_bad_peer_list_fails_before_anything_is_dialled(tmp_path, capsys):
    code = main(["--corpus-dir", str(tmp_path), "fetch", "--peer", "broken"])
    assert code == 1
    assert "cannot assemble the peer list" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["fetch", "--peer", "a=https://a"], ["a"]),
        (["fetch", "--builtin", "aws"], ["aws"]),
        (["fetch", "--peer", "a=https://a", "--builtin", "aws"], ["aws", "a"]),
        (["fetch"], ["gcp", "aws", "azure"]),
    ],
)
def test_naming_a_peer_suppresses_the_built_ins(argv, expected):
    """A run against one public agent must not silently dial two clouds."""
    from cards.cli import _specs, build_parser

    args = build_parser().parse_args(argv)
    assert [s.name for s in _specs(args)] == expected
