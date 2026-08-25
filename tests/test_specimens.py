"""The local card specimens, in-process, over a real ASGI transport.

No ports, no subprocess, no `run_mesh.sh` -- the app objects are imported and
dialled through httpx's ASGI transport, so this runs in CI on a machine where
those ports are already taken. Which they were: this repo's first run compared
another project's agents because both defaulted to 10001-10003.

Only the a2a-sdk specimens are exercised here. ADK's `to_a2a()` builds its
routes on startup and needs a running server, so the GCP specimen is covered by
`run_mesh.sh` and the stored corpus in `tests/corpus/adk.json` instead -- which
is a real card it really served, not a mock of one.
"""

import httpx
import pytest

from cards.fetch import fetch_card
from cards.review import review
from cards.spec import detect
from peers.registry import Peer

pytest.importorskip("a2a.server.routes")


@pytest.fixture(params=["aws", "azure"])
def specimen_app(request):
    from agents.common import public_url
    from agents.serving import build_agent_card, build_app

    port = {"aws": 11002, "azure": 11003}[request.param]
    card = build_agent_card(
        name="card_specimen", url=public_url(port), cloud=request.param
    )
    return request.param, build_app(card)


async def test_the_specimen_serves_a_card_on_the_current_path(specimen_app):
    cloud, app = specimen_app
    peer = Peer(name=cloud, endpoint="http://127.0.0.1:11002")
    result = await fetch_card(peer, transport=httpx.ASGITransport(app=app))
    assert result.ok
    assert result.path == "/.well-known/agent-card.json"


async def test_the_specimen_card_is_the_hybrid_shape(specimen_app):
    """Not an assertion about what is *right* -- a record of what a2a-sdk emits.

    If a future a2a-sdk stops back-filling the pre-1.0 fields, this test goes
    red and the change gets noticed, which is the entire value of pinning a
    measurement in a test rather than in a comment.
    """
    cloud, app = specimen_app
    peer = Peer(name=cloud, endpoint="http://127.0.0.1:11002")
    result = await fetch_card(peer, transport=httpx.ASGITransport(app=app))
    shape = detect(result.card)
    assert shape.label == "hybrid"
    assert shape.declared == "0.3"


async def test_the_specimen_card_has_no_errors_against_the_review(specimen_app):
    """The control has to be clean, or it controls for nothing."""
    cloud, app = specimen_app
    peer = Peer(name=cloud, endpoint="http://127.0.0.1:11002")
    result = review(await fetch_card(peer, transport=httpx.ASGITransport(app=app)))
    assert result.errors == []


async def test_the_specimen_advertises_a_configured_url_not_its_bind_address(
    monkeypatch, specimen_app
):
    """The bind-address bug, checked on the one stack that can avoid it."""
    monkeypatch.setenv("PUBLIC_URL", "https://agentcore.example/invocations/")
    from agents.common import public_url
    from agents.serving import build_agent_card, build_app

    card = build_agent_card(name="x", url=public_url(11002), cloud="aws")
    peer = Peer(name="aws", endpoint="https://agentcore.example/invocations")
    result = review(
        await fetch_card(peer, transport=httpx.ASGITransport(app=build_app(card)))
    )
    assert not [f for f in result.errors if f.code == "bind-address-on-card"]


async def test_the_agentcore_ping_contract_is_served(specimen_app):
    """`status` must be Healthy or HealthyBusy, and nothing else."""
    _, app = specimen_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "Healthy"}
