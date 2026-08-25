"""Where the cards disagree with each other.

``review`` asks whether one card is *correct*. This asks whether the cards are
*the same*, which is a different question with a different answer: every card
in a corpus can be perfectly conformant and still leave a client author with
five branches to write, because the spec permits all five.

Two outputs, and the split matters. An **axis** is a property every peer has a
value for -- shape, transports, declared capabilities -- and is worth showing
whether or not the peers agree, because the agreement is the interesting part
when it happens. A **divergence** is an axis where they disagree *and* the
disagreement costs a client something; it is a subset, promoted, so that a
table of forty identical rows does not hide the four that are not.
"""

from dataclasses import dataclass, field

from cards.model import Corpus, Specimen
from cards.review import Review
from cards.spec import KNOWN_FIELDS


@dataclass
class Axis:
    """One property, per peer, with whether they agreed."""

    key: str
    label: str
    values: dict[str, str]
    #: What a difference here costs whoever writes a client. Empty when a
    #: difference is merely descriptive.
    consequence: str = ""

    @property
    def distinct(self) -> list[str]:
        """Every value, empties included.

        Empty is a value here, not a gap. One runtime declaring its protocol
        version per interface while the others declare nothing there is exactly
        the difference a client author has to handle, and filtering empties out
        -- which this did until it was run against real cards on 2026-08-24 --
        reported that as unanimous agreement.
        """
        return sorted(set(self.values.values()))

    @property
    def agree(self) -> bool:
        return len(self.distinct) <= 1

    @property
    def unanimous_value(self) -> str:
        return self.distinct[0] if self.agree and self.distinct else ""


@dataclass
class Comparison:
    peers: list[str]
    axes: list[Axis]
    #: field name -> peers that carry it. Every field any peer had.
    field_presence: dict[str, list[str]] = field(default_factory=dict)
    #: Fields every peer had, and fields exactly one peer had.
    universal_fields: list[str] = field(default_factory=list)
    unique_fields: dict[str, str] = field(default_factory=dict)

    @property
    def divergences(self) -> list[Axis]:
        """Axes where the peers disagree and the disagreement has a cost."""
        return [a for a in self.axes if not a.agree and a.consequence]

    @property
    def agreements(self) -> list[Axis]:
        return [a for a in self.axes if a.agree and a.unanimous_value]


def _join(values) -> str:
    if not values:
        return ""
    if isinstance(values, list | tuple | set):
        return ", ".join(str(v) for v in sorted(values)) if values else ""
    return str(values)


#: Every axis, as (key, label, fact name, consequence). Data rather than code
#: so adding one is a line, and so the report can render them without knowing
#: what any of them mean.
_AXES: tuple[tuple[str, str, str, str], ...] = (
    (
        "shape",
        "card revision (from its keys)",
        "shape",
        ("a client must parse two different card layouts, and cannot tell which "
        "from the declared version"),
    ),
    (
        "declared_version",
        "protocolVersion as declared",
        "declared_version",
        "a client branching on this string branches wrongly for at least one peer",
    ),
    (
        "interface_versions",
        "protocolVersion declared per interface",
        "interface_versions",
        ("the version is declared in a different place per runtime, so a client "
        "has to look in both and pick a winner"),
    ),
    (
        "transports",
        "advertised transport",
        "transports",
        "a client that speaks one binding cannot reach every peer",
    ),
    (
        "capabilities",
        "declared capabilities",
        "capabilities",
        "streaming and push cannot be assumed uniformly across the mesh",
    ),
    ("input_modes", "defaultInputModes", "input_modes", ""),
    ("output_modes", "defaultOutputModes", "output_modes", ""),
    (
        "security_schemes",
        "securitySchemes",
        "security_schemes",
        "a client cannot learn from the cards how to authenticate to each peer",
    ),
    (
        "signed",
        "card signed",
        "signed",
        "provenance can be checked for some peers and not others",
    ),
    ("skill_count", "skills advertised", "skill_count", ""),
    (
        "skill_ids",
        "skill ids",
        "skill_ids",
        ("the same capability is selected by a different id per peer, so a "
        "router needs a per-peer table"),
    ),
    ("tags", "skill tags", "tags", ""),
    ("provider", "provider organisation", "provider", ""),
    (
        "extension_fields",
        "fields outside the spec",
        "extension_fields",
        "",
    ),
    ("bytes", "card size (bytes)", "bytes", ""),
)


def compare(reviews: list[Review]) -> Comparison:
    """Contrast every reviewed card that actually arrived.

    Cards that did not arrive are excluded rather than shown as blanks: an
    empty column reads as "this peer disagrees with everyone", which is the
    opposite of what a denied fetch means. They stay in the corpus and in the
    report's failure section, where the reason is legible.
    """
    usable = [r for r in reviews if r.facts]
    peers = [r.peer for r in usable]

    axes: list[Axis] = []
    for key, label, fact, consequence in _AXES:
        values = {r.peer: _join(r.facts.get(fact)) for r in usable}
        axes.append(Axis(key=key, label=label, values=values, consequence=consequence))

    presence: dict[str, list[str]] = {}
    for r in usable:
        for name in r.facts.get("fields", []):
            presence.setdefault(name, []).append(r.peer)

    universal = sorted(k for k, v in presence.items() if len(v) == len(peers)) if peers else []
    unique = {k: v[0] for k, v in sorted(presence.items()) if len(v) == 1 and len(peers) > 1}

    return Comparison(
        peers=peers,
        axes=axes,
        field_presence={k: sorted(v) for k, v in sorted(presence.items())},
        universal_fields=universal,
        unique_fields=unique,
    )


@dataclass
class FetchCost:
    """What discovery cost per peer, which no card records about itself.

    Worth a table of its own. A card fetched over ``entra-fic`` costs three
    round trips, one of them to a different cloud's identity provider, and the
    card is byte-identical to one fetched over an open port. That difference is
    invisible in every comparison above and is the one a latency budget cares
    about.
    """

    peer: str
    auth: str
    keyless: bool
    round_trips: int
    credential_ms: float
    discovery_ms: float
    total_ms: float
    paths_tried: int
    path: str
    request_id: str


def fetch_costs(corpus: Corpus) -> list[FetchCost]:
    return [_cost(s) for s in corpus.specimens]


def _cost(specimen: Specimen) -> FetchCost:
    credential_ms = sum(
        step.elapsed_ms for step in specimen.trace if step.phase == "credential"
    )
    discovery_ms = sum(
        step.elapsed_ms for step in specimen.trace if step.phase != "credential"
    )
    return FetchCost(
        peer=specimen.peer,
        auth=specimen.auth_used,
        keyless=specimen.keyless,
        round_trips=len(specimen.trace),
        credential_ms=credential_ms,
        discovery_ms=discovery_ms or sum(a.elapsed_ms for a in specimen.attempts),
        total_ms=credential_ms + (discovery_ms or sum(a.elapsed_ms for a in specimen.attempts)),
        paths_tried=len(specimen.attempts),
        path=specimen.path,
        request_id=specimen.request_id,
    )


def spec_coverage(reviews: list[Review]) -> dict[str, list[str]]:
    """Which spec-defined fields nobody serves.

    The inverse of the extension table, and the more useful half. A field the
    spec defines and no runtime emits is either dead in practice or a gap every
    vendor has -- and either way a client author should stop planning for it.
    """
    served: set[str] = set()
    for r in reviews:
        served.update(r.facts.get("fields", []))
    return {
        "served": sorted(served & KNOWN_FIELDS),
        "unserved": sorted(KNOWN_FIELDS - served),
    }
