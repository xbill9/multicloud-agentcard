"""What the A2A agent card is supposed to look like, per revision.

This is a *table*, not a validator. It is separate from ``review.py`` because
the two age differently: the review logic is stable and this file is wrong the
moment the spec moves, so it is worth being able to see all of the assumptions
in one place and date them.

Three shapes are in the wild at once, which is the reason this repo is
interesting at all:

``0.2``
    ``url`` at the top level, camelCase throughout, no ``protocolVersion``.

``0.3``
    adds ``protocolVersion``, ``preferredTransport``, ``additionalInterfaces``,
    ``signatures`` and ``security``/``securitySchemes``. ``url`` stays.

``1.0``
    replaces ``url`` + ``preferredTransport`` + ``additionalInterfaces`` with a
    single ``supportedInterfaces`` list, and renames ``security`` to
    ``securityRequirements``. Derived from the proto definition shipped in
    ``a2a.types.AgentCard`` -- see ``spec_fields_from_sdk()`` below, which
    re-derives it at runtime so this table can be checked rather than trusted.

**Measured 2026-08-24, and the reason the shapes are not mutually exclusive:**
``a2a-sdk`` 1.1.2 serves a *hybrid*. It emits the 1.0 ``supportedInterfaces``
list and then back-fills ``url``, ``preferredTransport`` and
``protocolVersion: "0.3"`` alongside it. A card from that stack therefore
declares 0.3 while carrying 1.0's shape, and any detector that stops at the
first match gets it wrong.
"""

from dataclasses import dataclass

#: Required in every revision. A card missing one of these is malformed, not
#: merely old.
REQUIRED_CORE: tuple[str, ...] = (
    "name",
    "description",
    "version",
    "capabilities",
    "defaultInputModes",
    "defaultOutputModes",
    "skills",
)

#: Fields that only make sense in the pre-1.0 shape.
LEGACY_FIELDS: tuple[str, ...] = (
    "url",
    "preferredTransport",
    "additionalInterfaces",
    "security",
    "supportsAuthenticatedExtendedCard",
)

#: Fields introduced by, or renamed in, 1.0.
CURRENT_FIELDS: tuple[str, ...] = (
    "supportedInterfaces",
    "securityRequirements",
)

#: Optional in every revision that has them.
OPTIONAL_FIELDS: tuple[str, ...] = (
    "protocolVersion",
    "provider",
    "iconUrl",
    "documentationUrl",
    "securitySchemes",
    "signatures",
)

KNOWN_FIELDS: frozenset[str] = frozenset(
    (*REQUIRED_CORE, *LEGACY_FIELDS, *CURRENT_FIELDS, *OPTIONAL_FIELDS)
)

#: A skill without these is not usable by a client: ``id`` is how it is
#: selected, and the rest are how a human or a router decides to.
SKILL_REQUIRED: tuple[str, ...] = ("id", "name", "description", "tags")
SKILL_OPTIONAL: tuple[str, ...] = (
    "examples",
    "inputModes",
    "outputModes",
    "security",
    "securityRequirements",
)
SKILL_KNOWN: frozenset[str] = frozenset((*SKILL_REQUIRED, *SKILL_OPTIONAL))

CAPABILITY_KNOWN: frozenset[str] = frozenset(
    {"streaming", "pushNotifications", "stateTransitionHistory", "extensions"}
)

INTERFACE_KNOWN: frozenset[str] = frozenset(
    {"url", "protocolBinding", "transport", "tenant", "protocolVersion"}
)

#: Transport names the spec defines. Anything else is a vendor extension and
#: worth naming as one rather than flagging as an error -- an unknown transport
#: is how a new binding arrives.
KNOWN_TRANSPORTS: frozenset[str] = frozenset(
    {"JSONRPC", "GRPC", "HTTP+JSON", "HTTP_JSON"}
)


@dataclass(frozen=True)
class Shape:
    """Which revision(s) a card's *structure* belongs to.

    ``current`` and ``legacy`` can both be true. That is not a bug in the
    detector; see the module docstring on a2a-sdk 1.1.2.

    ``declared`` and ``label`` are kept apart on purpose: one is what the card
    said about itself and the other is what its keys show. Collapsing them
    would delete the only evidence that a vendor's declaration and its wire
    format disagree, which is the finding most likely to matter to a client
    author.
    """

    #: The card carries 1.0's ``supportedInterfaces``.
    current: bool
    #: The card carries pre-1.0 top-level ``url`` / ``preferredTransport`` /
    #: ``additionalInterfaces``.
    legacy: bool
    #: Whatever the card *says* its protocol version is, verbatim. Empty when
    #: it does not say -- which is itself the 0.2 signature.
    declared: str
    #: The revision inferred from the keys alone.
    label: str

    @property
    def disagrees(self) -> bool:
        """The card declares one revision and is shaped like another."""
        if not self.declared:
            return False
        return not self.label.startswith(self.declared)


def detect(card: dict) -> Shape:
    """Read the shape off the keys, never off ``protocolVersion``.

    The declared version and the actual structure disagree in the field --
    measured, not hypothesised -- so a detector that trusts the declaration is
    reporting the vendor's intent rather than the wire. Both are recorded; only
    the structure decides.
    """
    current = "supportedInterfaces" in card
    legacy = any(
        key in card for key in ("url", "preferredTransport", "additionalInterfaces")
    )
    declared = str(card.get("protocolVersion") or "")

    if current and legacy:
        label = "hybrid"
    elif current:
        label = "1.0"
    elif legacy:
        # 0.2 has no protocolVersion and none of 0.3's additions. Decided here,
        # where the card is in hand.
        modern = bool(declared) or any(
            key in card
            for key in ("preferredTransport", "additionalInterfaces", "signatures")
        )
        label = "0.3" if modern else "0.2"
    else:
        label = "unrecognised"
    return Shape(current=current, legacy=legacy, declared=declared, label=label)


#: How each inferred label reads in a report. Kept out of `Shape` so the label
#: stays a short token that can be grouped on.
SHAPE_DESCRIPTIONS: dict[str, str] = {
    "0.2": "pre-0.3: top-level url, no protocolVersion",
    "0.3": "0.3: url + preferredTransport + additionalInterfaces",
    "1.0": "1.0: supportedInterfaces only",
    "hybrid": "1.0 supportedInterfaces plus pre-1.0 compatibility fields",
    "unrecognised": "no interface field of any revision",
}


def spec_fields_from_sdk() -> frozenset[str]:
    """Re-derive 1.0's field names from the installed ``a2a-sdk`` proto.

    So the table above can be *checked* rather than believed. The test suite
    asserts that every name this returns appears in ``KNOWN_FIELDS``, which
    turns "the spec moved and nobody noticed" from a silent wrong answer into a
    red test on the next `pip install`.
    """
    from a2a.types import AgentCard

    def camel(name: str) -> str:
        head, *tail = name.split("_")
        return head + "".join(part.title() for part in tail)

    return frozenset(camel(field.name) for field in AgentCard.DESCRIPTOR.fields)
