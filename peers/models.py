"""What a single HTTP round trip looked like.

Lifted whole from the research mesh this repo forked from, where it was one
model among many. Here it is the *only* wire model, and it carries more weight
because of it: a card fetch has no payload worth judging, so what a leg did on
the way to the card -- how many round trips, to whose identity provider, with
what status and whose request id -- is most of what there is to compare.

Deliberately never carries a token, a header or a response body. A trace that
must be redacted before it can be shown is a trace nobody shows.
"""

from datetime import datetime

from pydantic import BaseModel


class TraceStep(BaseModel):
    """One HTTP round trip made on one leg's behalf.

    The evidence layer. Everything else in this file is what the mesh
    *concluded*; this is what it *did*, and the difference matters because the
    interesting claims here are not about draft quality at all -- they are
    "this call crossed a cloud boundary" and "this call was authenticated".
    Both are invisible in a Draft, which looks identical whether it came from
    Bedrock over SigV4 or from a canned string two lines away.

    Deliberately never carries a token, a header or a response body. A trace
    that must be redacted before it can be shown is a trace nobody shows.
    """

    #: "credential" (an identity provider), "discovery" (agent-card fetch) or
    #: "invoke" (the A2A call itself). Enough to order a flow diagram without
    #: parsing URLs at render time.
    phase: str
    #: Human-readable, written by the code that made the call -- e.g. the auth
    #: boundary string, which already names the audience being asked for.
    label: str
    host: str
    path: str = ""
    method: str = "GET"
    status: int | None = None
    #: Wall clock, when the request left. Carried alongside `elapsed_ms`
    #: because the two answer different questions: elapsed says how long a hop
    #: took, and this says *when it happened relative to the others*, which is
    #: the only way to see that three legs really did run concurrently rather
    #: than one after another. A per-leg duration cannot show that.
    started_at: datetime | None = None
    elapsed_ms: float = 0.0
    #: Response body size from `content-length`, or None when the provider did
    #: not send one. Not measured by reading the body: an event hook runs
    #: before the stream is consumed, and reading it there would take the
    #: response away from the parser that is about to need it.
    bytes: int | None = None
    #: The provider's own identifier for this request, lifted from whichever
    #: header it uses -- `x-amzn-requestid`, `x-ms-request-id`, and so on.
    #: The single most valuable field here, because it is the only one an
    #: outside reader can check: every other column is this process describing
    #: itself, while this one can be pasted into CloudWatch or Cloud Logging
    #: and either finds the same call on the provider's side or does not.
    #: Empty when the provider sent no such header.
    request_id: str = ""
    ok: bool = True
    #: Only on failure, and only the provider's own words. This is the field
    #: the predecessor series kept discarding and kept paying for.
    detail: str = ""
