"""Every check in `cards.review`, over cards two real runtimes served."""

from cards.model import Specimen
from cards.review import ERROR, NOTE, WARNING, review


def _specimen(card: dict | None, **kwargs) -> Specimen:
    import json

    return Specimen(
        peer=kwargs.pop("peer", "p"),
        endpoint=kwargs.pop("endpoint", "https://agent.example"),
        raw=json.dumps(card) if card is not None else "",
        card=card,
        **kwargs,
    )


def _codes(result) -> set[str]:
    return {f.code for f in result.findings}


def test_a_card_that_never_arrived_is_one_error_and_no_facts():
    result = review(_specimen(None, error="403 on /.well-known/agent-card.json"))
    assert _codes(result) == {"no-card"}
    assert result.facts == {}
    # Nothing downstream should be tempted to compare it with a real card.
    assert result.shape is None


def test_real_adk_card_reports_version_declared_per_interface(adk_card):
    result = review(_specimen(adk_card))
    assert "version-per-interface" in _codes(result)
    assert result.facts["interface_versions"] == ["1.0"]
    assert result.facts["declared_version"] == ""


def test_real_a2a_sdk_card_reports_the_shape_mismatch(hybrid_card):
    result = review(_specimen(hybrid_card))
    assert "version-shape-mismatch" in _codes(result)
    assert [f.severity for f in result.findings if f.code == "version-shape-mismatch"] == [
        WARNING
    ]


def test_missing_required_field_is_an_error(hybrid_card):
    del hybrid_card["skills"]
    result = review(_specimen(hybrid_card))
    assert any(f.code == "missing-required" and f.field == "skills" for f in result.errors)


def test_present_but_empty_required_field_is_also_an_error(hybrid_card):
    """Worse than absent: an `in` check sails past it and fails further away."""
    hybrid_card["skills"] = []
    result = review(_specimen(hybrid_card))
    assert any(f.code == "empty-required" for f in result.errors)


def test_loopback_url_on_a_remote_card_is_an_error(hybrid_card):
    """The bind-address finding this repo was forked to chase."""
    hybrid_card["url"] = "http://127.0.0.1:8080"
    hybrid_card["supportedInterfaces"][0]["url"] = "http://127.0.0.1:8080"
    result = review(_specimen(hybrid_card, endpoint="https://agent.example"))
    assert any(f.code == "bind-address-on-card" for f in result.errors)


def test_loopback_url_is_not_flagged_when_the_card_came_from_loopback(hybrid_card):
    """The local specimens must not produce a permanent false positive."""
    hybrid_card["url"] = "http://127.0.0.1:11002"
    hybrid_card["supportedInterfaces"][0]["url"] = "http://127.0.0.1:11002"
    result = review(_specimen(hybrid_card, endpoint="http://127.0.0.1:11002"))
    assert "bind-address-on-card" not in _codes(result)


def test_hybrid_card_whose_two_endpoint_copies_disagree_is_an_error(hybrid_card):
    hybrid_card["url"] = "https://a.example"
    hybrid_card["supportedInterfaces"][0]["url"] = "https://b.example"
    result = review(_specimen(hybrid_card))
    assert any(f.code == "interface-drift" for f in result.errors)


def test_authenticated_fetch_of_a_card_naming_no_scheme_is_a_warning(hybrid_card):
    result = review(_specimen(hybrid_card, auth_used="entra-fic", auth_configured="entra-fic"))
    assert any(f.code == "undeclared-auth" for f in result.warnings)


def test_a_leg_that_fell_back_to_no_credential_is_an_error(hybrid_card):
    """Its card is not comparable with the authenticated ones, and says so."""
    result = review(_specimen(hybrid_card, auth_configured="aws-sigv4", auth_used="none"))
    assert any(f.code == "auth-fell-back" for f in result.errors)


def test_duplicate_skill_ids_are_an_error(hybrid_card):
    hybrid_card["skills"] = [hybrid_card["skills"][0], dict(hybrid_card["skills"][0])]
    result = review(_specimen(hybrid_card))
    assert any(f.code == "duplicate-skill-id" for f in result.errors)


def test_a_mode_that_is_not_a_media_type_is_a_warning(hybrid_card):
    hybrid_card["defaultInputModes"] = ["text"]
    result = review(_specimen(hybrid_card))
    assert any(f.code == "non-media-type" for f in result.warnings)


def test_vendor_fields_are_a_note_not_an_error(hybrid_card):
    hybrid_card["x-vendor-thing"] = 1
    result = review(_specimen(hybrid_card))
    assert any(f.code == "vendor-fields" and f.severity == NOTE for f in result.findings)
    assert result.facts["extension_fields"] == ["x-vendor-thing"]


def test_an_unknown_transport_is_a_note_because_that_is_how_new_ones_arrive(hybrid_card):
    hybrid_card["supportedInterfaces"][0]["protocolBinding"] = "WEBSOCKET"
    result = review(_specimen(hybrid_card))
    assert any(f.code == "unknown-transport" and f.severity == NOTE for f in result.findings)


def test_a_card_with_no_endpoint_at_all_is_an_error():
    result = review(_specimen({"name": "x", "description": "d", "version": "1"}))
    assert any(f.code == "no-interface" for f in result.errors)


def test_review_never_raises_on_structurally_wrong_types():
    """A malformed card must produce findings, not a traceback."""
    result = review(
        _specimen(
            {
                "name": "x",
                "capabilities": "not-an-object",
                "skills": "not-a-list",
                "defaultInputModes": "not-a-list",
                "supportedInterfaces": ["not-an-object"],
            }
        )
    )
    assert {"bad-capabilities", "bad-skills", "bad-modes", "bad-interface"} <= _codes(result)


def test_findings_are_ordered_errors_first(hybrid_card):
    del hybrid_card["name"]
    result = review(_specimen(hybrid_card))
    severities = [f.severity for f in result.findings]
    assert severities == sorted(severities, key=lambda s: {ERROR: 0, WARNING: 1, NOTE: 2}[s])
