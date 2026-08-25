"""What one fetch produced, kept raw.

The rule this whole repo turns on: **store the bytes, derive everything else.**
A specimen holds the exact body the server sent, and every later step -- the
conformance review, the cross-peer diff, the report -- is a pure function of
that body plus the HTTP metadata around it. Parsing on the way in would be
convenient and would throw away the finding: a field a vendor spells
differently, an extra key no client models, a body that is not JSON at all.
"""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from peers.models import TraceStep

#: Schema version for a stored specimen file. Bumped whenever `Specimen` gains
#: or loses a field, so a corpus recorded by an older build can be excluded
#: from an aggregate rather than silently mis-read.
SPECIMEN_VERSION = 1


class Attempt(BaseModel):
    """One HTTP GET against one candidate discovery path.

    Every attempt is kept, including the ones that 404, because *which path a
    runtime answers on* is itself a comparison axis. A peer that serves
    ``/.well-known/agent.json`` and 404s the current path is telling you its
    protocol revision before the card is even parsed.
    """

    path: str
    url: str
    status: int | None = None
    elapsed_ms: float = 0.0
    bytes: int | None = None
    content_type: str = ""
    request_id: str = ""
    ok: bool = False
    #: The provider's own words on failure, never a paraphrase.
    detail: str = ""


class Specimen(BaseModel):
    """One peer's card, as fetched, with the evidence for how it was fetched."""

    version: int = SPECIMEN_VERSION
    peer: str
    endpoint: str
    runtime: str = ""
    #: The mode configured for this peer, and the mode the credential object
    #: actually reported. Divergence between them means a leg fell back to an
    #: unauthenticated fetch, which makes its card not comparable with the
    #: others -- an open card and a privileged card can differ for reasons that
    #: have nothing to do with the runtime.
    auth_configured: str = "none"
    auth_used: str = "none"
    keyless: bool = True
    fetched_at: datetime | None = None
    #: The path that answered, empty if none did.
    path: str = ""
    url: str = ""
    status: int | None = None
    elapsed_ms: float = 0.0
    content_type: str = ""
    request_id: str = ""
    #: The body exactly as received. Not re-serialised from `card`: a
    #: round-trip through Python would normalise key order, unicode escaping
    #: and number formatting, all of which are things worth comparing.
    raw: str = ""
    #: The body parsed, when it was JSON *and* an object. `None` covers three
    #: different failures and `parse_error` says which.
    card: dict[str, Any] | None = None
    parse_error: str = ""
    attempts: list[Attempt] = Field(default_factory=list)
    #: Every HTTP round trip the fetch caused, credential mints included. A
    #: card fetched over `entra-fic` costs three requests, one of them to a
    #: different cloud, and that is invisible in the card itself.
    trace: list[TraceStep] = Field(default_factory=list)
    #: Set when no path answered. The card is then absent and the specimen is
    #: still worth keeping -- a peer that denies discovery is a result.
    error: str = ""
    failure_kind: str = ""

    @property
    def ok(self) -> bool:
        return self.card is not None

    @property
    def byte_count(self) -> int:
        return len(self.raw.encode())

    def pretty(self) -> str:
        """The card re-rendered for a human. Never used for comparison."""
        if self.card is None:
            return self.raw
        return json.dumps(self.card, indent=2, sort_keys=True, ensure_ascii=False)


class Corpus(BaseModel):
    """Every specimen from one run, plus what the run was.

    Written whole. The alternative -- a file per peer -- loses the fact that
    these particular cards were fetched *together*, which is the only reason a
    difference between them is attributable to the runtime rather than to two
    weeks having passed.
    """

    run_id: str
    started_at: datetime
    elapsed_ms: float = 0.0
    specimens: list[Specimen] = Field(default_factory=list)

    @property
    def fetched(self) -> list[Specimen]:
        return [s for s in self.specimens if s.ok]

    @property
    def failed(self) -> list[Specimen]:
        return [s for s in self.specimens if not s.ok]
