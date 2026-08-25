"""AZURE card specimen: the a2a-sdk reference routes, nothing else.

Deployed to Container Apps. Locally it is one of two stacks on the bench, and the
one that matters as a control: whatever this card looks like is what the
protocol's own reference server emits, so a field that differs on a *deployed*
AZURE card differs because of the runtime, not the SDK.

    python -m agents.azure.server

Environment: ``PORT`` (11003), ``PUBLIC_URL``, ``HOST``.
"""

import os

from agents.common import AGENT_NAME, public_url
from agents.serving import build_agent_card, build_app
from peers.telemetry import setup as setup_telemetry

DEFAULT_PORT = 11003
CLOUD = "azure"

# Before anything builds an agent: the instrumented httpx client has to be in
# place before a vendor SDK constructs its own, or that SDK's calls are
# invisible to the trace.
setup_telemetry("card-" + CLOUD)

card = build_agent_card(
    name=AGENT_NAME, url=public_url(DEFAULT_PORT), cloud=CLOUD
)
app = build_app(card)


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", str(DEFAULT_PORT))),
    )


if __name__ == "__main__":
    main()
