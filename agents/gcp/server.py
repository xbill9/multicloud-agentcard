"""GCP card specimen: whatever ADK's ``to_a2a()`` decides a card looks like.

The only local agent that does not touch the a2a-sdk serving scaffolding --
ADK builds its own Starlette app *and its own card*, from the agent object,
with no way to say what should go on it. That is not a limitation to work
around here; it is the specimen. Two stacks, one trivial agent, two different
cards, on one machine, before a single cloud is involved.

The known one, left un-patched on purpose: ``to_a2a(host, port)`` writes the
*bind* address into the card, so the URL a remote client reads is the address
the server bound locally. Fixing it here would delete the finding.

    python -m agents.gcp.server

Environment: ``PORT`` (11001), ``HOST``.
"""

import logging
import os

from starlette.responses import JSONResponse

from agents.common import AGENT_NAME, DESCRIPTION, SKILL_DESCRIPTION
from peers.telemetry import instrument_app, telemetry_summary
from peers.telemetry import setup as setup_telemetry

logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)

DEFAULT_PORT = 11001
CLOUD = "gcp"

setup_telemetry("card-" + CLOUD)


def _agent():
    """A credential-free ADK agent: no model is ever called.

    ``to_a2a`` needs an agent to derive a card from, not a working one, and
    this repo never sends the specimen a message it has to think about. Keeping
    it model-free is what lets the local mesh run with no cloud project, no
    key, and no spend -- which is the only reason it can be the control.
    """
    from google.adk.agents import BaseAgent
    from google.adk.events import Event
    from google.genai import types

    class Echo(BaseAgent):
        async def _run_async_impl(self, ctx):
            yield Event(
                author=self.name,
                content=types.Content(role="model", parts=[types.Part(text="ok")]),
            )

    return Echo(name=AGENT_NAME, description=f"{DESCRIPTION}. {SKILL_DESCRIPTION}.")


def build():
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    a2a_app = to_a2a(
        _agent(),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", str(DEFAULT_PORT))),
    )

    async def health(request):
        return JSONResponse(
            {"status": "ok", "agent": AGENT_NAME, "telemetry": telemetry_summary()}
        )

    a2a_app.add_route("/health", health, methods=["GET"])
    instrument_app(a2a_app)
    return a2a_app


app = build()


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", str(DEFAULT_PORT))),
    )


if __name__ == "__main__":
    main()
