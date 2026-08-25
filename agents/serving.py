"""a2a-sdk 1.x serving scaffolding for the local card specimens.

Two of the three local agents sit on the reference Starlette routes. The third
(GCP) does not, because ADK's ``to_a2a()`` builds its own app and its own card
-- and that difference is the entire point of keeping a local mesh at all. Two
stacks on one machine, serving cards for the same trivial agent, already
disagree; the three deployed runtimes disagree more, and having a control on
the bench is what tells a *runtime* difference from an *SDK* difference.
"""

from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Role
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, VERSION_HEADER
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from agents.common import (
    CARD_VERSION,
    DESCRIPTION,
    SKILL_DESCRIPTION,
    SKILL_ID,
)
from peers.telemetry import instrument_app, telemetry_summary


class EchoExecutor(AgentExecutor):
    """The whole agent. It exists so the card is not a lie.

    A card advertising a skill nothing implements would still be fetchable, and
    every comparison in this repo would still run -- which is precisely why the
    executor is here: the specimen has to be a real A2A agent, or the local
    control stops controlling for anything.
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            new_text_message(context.get_user_input(), role=Role.ROLE_AGENT)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            new_text_message("nothing to cancel", role=Role.ROLE_AGENT)
        )


def build_agent_card(*, name: str, url: str, cloud: str) -> AgentCard:
    """The specimen card, filled in as completely as the SDK's types allow.

    Deliberately *not* minimal. A card with only the required fields tells you
    nothing about which optional fields a runtime drops in transit, and "the
    field was never set" and "the field was set and did not survive" are the
    two answers this repo has to be able to tell apart.
    """
    return AgentCard(
        name=name,
        description=DESCRIPTION,
        version=CARD_VERSION,
        documentation_url="https://github.com/xbill9/multicloud-agentcard",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        # The advertised URL is configuration, never the bind address.
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC")],
        skills=[
            AgentSkill(
                id=SKILL_ID,
                name="echo",
                description=SKILL_DESCRIPTION,
                tags=["echo", "diagnostic", f"cloud:{cloud}"],
                examples=["ping"],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        ],
    )


def build_app(card: AgentCard) -> Starlette:
    async def health(request):
        return JSONResponse(
            {
                "status": "ok",
                "agent": card.name,
                "telemetry": telemetry_summary(),
            }
        )

    async def ping(request):
        """AgentCore Runtime's health contract.

        Required verbatim: ``status`` must be ``Healthy`` or ``HealthyBusy``.
        Deliberately omits ``time_of_last_update`` -- a timestamp that advances
        on every ping reads as a continuous status change, which stops the idle
        session timeout from ever firing and leaks sessions until MaxLifetime.
        """
        return JSONResponse({"status": "Healthy"})

    handler = DefaultRequestHandler(
        agent_executor=EchoExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    app = Starlette(
        routes=[
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, "/"),
            Route("/health", health, methods=["GET"]),
            Route("/ping", ping, methods=["GET"]),
        ],
        middleware=[Middleware(_AssumeCurrentProtocolVersion)],
    )
    instrument_app(app)
    return app


class _AssumeCurrentProtocolVersion(BaseHTTPMiddleware):
    """Treat a missing ``A2A-Version`` header as the current version, not 0.3.

    a2a-sdk reads the protocol version from that header and, when it is absent,
    assumes ``0.3`` and then rejects the request its own handler cannot serve:
    ``A2A version '0.3' is not supported by this handler. Expected version
    '1.0'``. A missing header is not evidence of an old client -- it is no
    evidence at all.

    Carried over from the mesh because it is a *discovery-adjacent* finding and
    this repo is about discovery: **AgentCore does not forward the header**.
    Cloud Run and Container Apps pass it through untouched, so the same client,
    the same a2a-sdk on both ends, and the same server code succeed on two
    clouds and fail on the third.

    Scoped deliberately to *absent*: a header that says 0.3 is a real client
    statement and is still rejected.
    """

    async def dispatch(self, request, call_next):
        if VERSION_HEADER.lower() not in {k.lower() for k in request.headers}:
            request.scope["headers"] = [
                *request.scope["headers"],
                (VERSION_HEADER.lower().encode(), PROTOCOL_VERSION_CURRENT.encode()),
            ]
        return await call_next(request)
