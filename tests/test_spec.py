"""The spec table, and whether it still matches the SDK it claims to describe."""

from cards.spec import KNOWN_FIELDS, detect, spec_fields_from_sdk


def test_sdk_fields_are_all_in_the_table():
    """The check that makes this table maintainable rather than merely written.

    ``spec_fields_from_sdk`` re-derives 1.0's field names from the installed
    proto. If a2a-sdk adds one and this table does not know it, that field
    would be reported to every user as a vendor extension -- a wrong answer
    with no symptom. This turns it into a red test on the next install.
    """
    missing = spec_fields_from_sdk() - KNOWN_FIELDS
    assert not missing, f"a2a-sdk knows fields this repo does not: {sorted(missing)}"


def test_adk_card_is_pure_1_0(adk_card):
    shape = detect(adk_card)
    assert shape.label == "1.0"
    assert shape.current and not shape.legacy
    # ADK declares nothing at the top level; the version lives per interface.
    assert shape.declared == ""


def test_a2a_sdk_card_is_hybrid(hybrid_card):
    shape = detect(hybrid_card)
    assert shape.label == "hybrid"
    assert shape.current and shape.legacy
    assert shape.declared == "0.3"
    # Declares 0.3, is shaped like 1.0. The measurement this repo exists for.
    assert shape.disagrees


def test_legacy_card_without_0_3_markers_is_0_2(legacy_card):
    assert detect(legacy_card).label == "0.2"


def test_legacy_card_with_0_3_markers_is_0_3(legacy_card):
    assert detect({**legacy_card, "preferredTransport": "JSONRPC"}).label == "0.3"


def test_card_with_no_endpoint_field_is_unrecognised():
    assert detect({"name": "x"}).label == "unrecognised"


def test_shape_does_not_disagree_when_it_cannot_know():
    """No declaration is not a disagreement."""
    assert not detect({"supportedInterfaces": []}).disagrees
