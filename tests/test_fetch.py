"""The fetcher, against responses no live cloud will produce on demand.

Every case here is one this repo would otherwise have to wait for: a card
served only on the 0.2 path, a 403 with a real AWS body, a 200 carrying HTML.
"""

import json

import httpx
import pytest

from cards.fetch import CARD_PATHS, fetch_all, fetch_card
from peers.errors import FailureKind
from peers.registry import Peer

CARD = {
    "name": "x",
    "description": "d",
    "version": "1",
    "capabilities": {},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [{"id": "s", "name": "s", "description": "d", "tags": ["t"]}],
    "supportedInterfaces": [{"url": "https://a.example", "protocolBinding": "JSONRPC"}],
}


def _peer(**kwargs) -> Peer:
    return Peer(name=kwargs.pop("name", "p"), endpoint=kwargs.pop("endpoint", "https://a.example"), **kwargs)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_current_path_answers_in_one_request():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=CARD)

    specimen = await fetch_card(_peer(), transport=_transport(handler))
    assert specimen.ok
    assert seen == ["/.well-known/agent-card.json"]
    assert specimen.path == "/.well-known/agent-card.json"
    assert len(specimen.attempts) == 1


async def test_a_404_on_the_current_path_falls_through_to_the_legacy_one():
    """A runtime a revision behind is a finding, not an outage."""

    def handler(request):
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(200, json=CARD)
        return httpx.Response(404)

    specimen = await fetch_card(_peer(), transport=_transport(handler))
    assert specimen.ok
    assert specimen.path == "/.well-known/agent.json"
    assert [a.path for a in specimen.attempts] == list(CARD_PATHS)


async def test_a_403_stops_the_search_and_keeps_the_provider_body():
    """Walking on after a denial buries the one attempt that explained itself."""
    body = "User: arn:aws:sts::1:assumed-role/x is not authorized to perform: bedrock-agentcore:GetAgentCard"

    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(403, text=body)

    specimen = await fetch_card(_peer(), transport=_transport(handler))
    assert not specimen.ok
    assert calls == ["/.well-known/agent-card.json"], "a denial is not a reason to try elsewhere"
    assert specimen.failure_kind == FailureKind.AUTHENTICATION.value
    assert "GetAgentCard" in specimen.error, "the provider's own words must survive"


async def test_a_200_carrying_html_is_a_failure_with_the_body_kept():
    """The failure most likely to be read as success: every status check passes."""
    html = "<!doctype html><title>Sign in</title>"

    specimen = await fetch_card(
        _peer(), transport=_transport(lambda r: httpx.Response(200, text=html))
    )
    assert not specimen.ok
    assert specimen.card is None
    assert "not JSON" in specimen.parse_error
    assert specimen.raw == html, "the bytes are the evidence and must be kept"


async def test_a_200_carrying_a_json_array_is_a_failure():
    specimen = await fetch_card(
        _peer(), transport=_transport(lambda r: httpx.Response(200, json=[1, 2]))
    )
    assert not specimen.ok
    assert "not an object" in specimen.parse_error


async def test_the_raw_body_is_kept_verbatim_not_reserialised():
    """Key order, spacing and escaping are all things worth comparing."""
    body = '{"name":"x","description":"d","version":"1","capabilities":{},"defaultInputModes":[],"defaultOutputModes":[],"skills":[],"url":"https://a.example"}'

    specimen = await fetch_card(
        _peer(),
        transport=_transport(
            lambda r: httpx.Response(200, content=body, headers={"content-type": "application/json"})
        ),
    )
    assert specimen.raw == body
    assert specimen.card == json.loads(body)


async def test_a_peer_path_is_tried_before_the_standard_ones():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=CARD) if len(seen) == 1 else httpx.Response(404)

    await fetch_card(_peer(card_paths=("/card",)), transport=_transport(handler))
    assert seen[0] == "/card"


async def test_a_transport_failure_is_recorded_not_raised():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    specimen = await fetch_card(_peer(), transport=_transport(handler))
    assert not specimen.ok
    assert all(not a.ok for a in specimen.attempts)
    assert "connection refused" in " ".join(a.detail for a in specimen.attempts)


async def test_every_round_trip_lands_in_the_trace():
    def handler(request):
        return httpx.Response(404) if "agent-card" in request.url.path else httpx.Response(
            200, json=CARD
        )

    specimen = await fetch_card(_peer(), transport=_transport(handler))
    assert len(specimen.trace) == 2
    assert {step.phase for step in specimen.trace} == {"discovery"}


async def test_one_peer_failing_degrades_the_run_rather_than_failing_it():
    def handler(request):
        if request.url.host == "denied.example":
            return httpx.Response(403, text="nope")
        return httpx.Response(200, json=CARD)

    corpus = await fetch_all(
        [
            _peer(name="ok", endpoint="https://ok.example"),
            _peer(name="denied", endpoint="https://denied.example"),
        ],
        transport=_transport(handler),
    )
    assert len(corpus.specimens) == 2
    assert [s.peer for s in corpus.fetched] == ["ok"]
    assert [s.peer for s in corpus.failed] == ["denied"]


async def test_the_specimen_reports_configured_and_used_auth_separately():
    """A leg that silently fetched an open card must not look federated."""
    peer = Peer(name="p", endpoint="https://a.example", auth="entra-fic", credential=None)
    specimen = await fetch_card(
        peer, transport=_transport(lambda r: httpx.Response(200, json=CARD))
    )
    assert specimen.auth_configured == "entra-fic"
    assert specimen.auth_used == "none"


@pytest.mark.parametrize("status", [401, 403])
async def test_both_denial_statuses_are_terminal(status):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, text="")

    await fetch_card(_peer(), transport=_transport(handler))
    assert len(calls) == 1


# The phase label. `cards/fetch.py` states the rule outright: this repo never
# invokes anything, so an `invoke` row in a phase breakdown is a round trip
# that cannot exist. A peer whose endpoint carries a path prefix of its own
# used to produce exactly that.


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",
        # AgentCore serves the card under the same /invocations/ path the calls
        # use. Measured 2026-08-25: this was filed as `invoke` on every run.
        "/runtimes/arn%3Aaws%3Abedrock-agentcore%3A.../invocations/.well-known/agent-card.json",
    ],
)
def test_a_card_fetch_is_discovery_however_the_endpoint_is_prefixed(path):
    from peers.trace import _is_card_path

    assert _is_card_path(path)


@pytest.mark.parametrize("path", ["/", "/messages", "/invocations/", "/agent-card.json"])
def test_anything_that_is_not_a_card_path_is_not_discovery(path):
    from peers.trace import _is_card_path

    assert not _is_card_path(path)
