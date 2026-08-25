"""What every local agent says about itself, and where it says it is.

The forked research mesh had a large module here: prompts, a search budget, a
draft renderer, a fault-injection switch. None of it survives, because an
agent whose only job is to *have a card* never answers a brief. What is left
is the identity that goes on the card and the one hard-won rule about the URL
written into it.
"""

import os

AGENT_NAME = "card_specimen"

DESCRIPTION = (
    "A minimal A2A agent that exists to be discovered: it publishes a card and "
    "echoes whatever it is sent"
)

SKILL_ID = "echo"
SKILL_DESCRIPTION = "Return the text it was given, unchanged"

#: Bumped when anything on the card changes, so a stored specimen can be told
#: apart from a later one without diffing every field.
CARD_VERSION = "1.0.0"


def public_url(default_port: int) -> str:
    """The URL this agent advertises on its card.

    Deliberately explicit, and the reason this fork exists. An agent behind
    Cloud Run, AgentCore, or Container Apps is reached at a hostname it cannot
    infer from its own socket, so a card that advertises the *bind* address is
    unreachable to every remote client. Whether a given runtime's card gets
    this right is one of the things `cards compare` is looking at -- so the
    two local specimens get it right on purpose, to be the control.
    """
    if url := os.getenv("PUBLIC_URL"):
        return url.rstrip("/")
    host = os.getenv("HOST", "127.0.0.1")
    port = os.getenv("PORT", str(default_port))
    return f"http://{host}:{port}"
