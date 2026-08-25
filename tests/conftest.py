"""Card fixtures, and the one rule about them.

Every synthetic card here is *derived from a real one*. `HYBRID` is what
a2a-sdk 1.1.2 actually served on 2026-08-24 and `ADK` is what ADK's `to_a2a()`
actually served the same minute, both trimmed. Inventing a card to test a
check against is how a check ends up correct about a card no runtime emits.

`tests/corpus/` holds the untrimmed originals.
"""

import json
from pathlib import Path

import pytest

CORPUS = Path(__file__).parent / "corpus"


def _card(name: str) -> dict:
    return json.loads((CORPUS / name).read_text())


@pytest.fixture
def adk_card() -> dict:
    """ADK to_a2a: pure 1.0 shape, protocolVersion inside the interface."""
    return _card("adk.json")


@pytest.fixture
def hybrid_card() -> dict:
    """a2a-sdk 1.1.2: 1.0 supportedInterfaces plus 0.3 compatibility fields."""
    return _card("a2a-sdk.json")


@pytest.fixture
def legacy_card() -> dict:
    """The 0.2 shape: top-level url, nothing else about transport or version."""
    return {
        "name": "legacy",
        "description": "a 0.2-era card",
        "version": "1.0.0",
        "url": "https://legacy.example/agent",
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {"id": "s", "name": "s", "description": "d", "tags": ["t"]}
        ],
    }
