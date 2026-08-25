"""Contrast, over the two cards the local specimens really served."""

from datetime import UTC, datetime

from cards.compare import compare, fetch_costs, spec_coverage
from cards.model import Corpus, Specimen
from cards.review import review


def _reviews(*cards):
    import json

    return [
        review(
            Specimen(
                peer=name,
                endpoint="https://a.example",
                raw=json.dumps(card),
                card=card,
            )
        )
        for name, card in cards
    ]


def test_the_two_real_stacks_diverge_on_where_the_version_is_declared(adk_card, hybrid_card):
    result = compare(_reviews(("gcp", adk_card), ("aws", hybrid_card)))
    keys = {axis.key for axis in result.divergences}
    assert "shape" in keys
    assert "declared_version" in keys
    assert "interface_versions" in keys


def test_an_absent_value_counts_as_a_value(adk_card, hybrid_card):
    """One runtime declaring nothing where another declares 1.0 is a difference.

    Filtering empties out reported that as unanimous agreement, which is how
    the first real run of this tool hid its most interesting finding.
    """
    result = compare(_reviews(("gcp", adk_card), ("aws", hybrid_card)))
    axis = next(a for a in result.axes if a.key == "interface_versions")
    assert axis.values == {"gcp": "1.0", "aws": ""}
    assert not axis.agree


def test_identical_cards_agree_on_every_axis(hybrid_card):
    result = compare(_reviews(("a", hybrid_card), ("b", dict(hybrid_card))))
    assert result.divergences == []
    assert all(axis.agree for axis in result.axes)


def test_field_presence_names_which_peers_carry_each_key(adk_card, hybrid_card):
    result = compare(_reviews(("gcp", adk_card), ("aws", hybrid_card)))
    assert result.field_presence["skills"] == ["aws", "gcp"]
    # `url` is the pre-1.0 compatibility field only a2a-sdk back-fills.
    assert result.field_presence["url"] == ["aws"]
    assert result.unique_fields["url"] == "aws"


def test_universal_fields_are_the_ones_every_peer_served(adk_card, hybrid_card):
    result = compare(_reviews(("gcp", adk_card), ("aws", hybrid_card)))
    assert "name" in result.universal_fields
    assert "url" not in result.universal_fields


def test_a_card_that_never_arrived_is_excluded_not_blanked(hybrid_card):
    """An empty column reads as 'this peer disagrees with everyone'."""
    import json

    reviews = [
        review(Specimen(peer="ok", endpoint="https://a", raw=json.dumps(hybrid_card), card=hybrid_card)),
        review(Specimen(peer="denied", endpoint="https://b", error="403")),
    ]
    result = compare(reviews)
    assert result.peers == ["ok"]


def test_spec_coverage_names_the_fields_nobody_serves(adk_card, hybrid_card):
    coverage = spec_coverage(_reviews(("gcp", adk_card), ("aws", hybrid_card)))
    assert "name" in coverage["served"]
    assert "signatures" in coverage["unserved"]
    assert not set(coverage["served"]) & set(coverage["unserved"])


def test_fetch_cost_separates_the_credential_mint_from_the_card_fetch():
    """The whole point of the cost table: this is on no card."""
    from peers.models import TraceStep

    specimen = Specimen(
        peer="azure",
        endpoint="https://a.example",
        auth_used="entra-fic",
        keyless=True,
        trace=[
            TraceStep(phase="credential", label="gcp metadata mint", host="metadata", elapsed_ms=40),
            TraceStep(phase="credential", label="entra exchange", host="login", elapsed_ms=120),
            TraceStep(phase="discovery", label="GET card", host="a.example", elapsed_ms=30),
        ],
    )
    corpus = Corpus(run_id="r", started_at=datetime.now(UTC), specimens=[specimen])
    cost = fetch_costs(corpus)[0]
    assert cost.round_trips == 3
    assert cost.credential_ms == 160
    assert cost.discovery_ms == 30
    assert cost.total_ms == 190
