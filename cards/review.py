"""Read one card properly: what it says, what it omits, and what it gets wrong.

Findings carry a severity and a stable code. The code is the important half --
a report is read once and a *diff between two reports* is read every time after
that, and codes are what make two runs comparable when the prose around them
has been reworded.

Three severities, and the boundary between them is deliberate:

``error``
    a client that follows the card is broken by it. A missing required field,
    an advertised URL nothing can dial.

``warning``
    the card is usable and something about it will cost someone an afternoon.
    A declared version that does not match the structure; a private agent
    advertising no security scheme.

``note``
    a true observation with no defect attached. Vendor extensions, absent
    optional fields, transports outside the spec's list. Notes are where the
    compare-and-contrast actually lives, so they are not noise to be filtered
    -- they are the point, and they are separated from the defects only so the
    defects stay findable.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from cards.model import Specimen
from cards.spec import (
    CAPABILITY_KNOWN,
    INTERFACE_KNOWN,
    KNOWN_FIELDS,
    KNOWN_TRANSPORTS,
    REQUIRED_CORE,
    SHAPE_DESCRIPTIONS,
    SKILL_KNOWN,
    SKILL_REQUIRED,
    Shape,
    detect,
)

ERROR = "error"
WARNING = "warning"
NOTE = "note"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, NOTE: 2}

#: Hosts that mean "this machine", which is never the machine reading the card.
_LOOPBACK = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "[::1]"}


@dataclass(frozen=True)
class Finding:
    peer: str
    severity: str
    code: str
    title: str
    detail: str = ""
    #: Dotted path into the card, e.g. ``skills[1].tags``. Empty for findings
    #: about the card as a whole.
    field: str = ""

    @property
    def rank(self) -> int:
        return _SEVERITY_ORDER.get(self.severity, 9)


@dataclass
class Review:
    """One card, read. ``facts`` is what the comparison joins on."""

    peer: str
    shape: Shape | None
    findings: list[Finding]
    #: Flattened, comparable properties of the card: field presence, skill
    #: ids, transports, modes. Derived once here so ``compare`` never has to
    #: reach back into raw JSON and re-learn the revision differences.
    facts: dict

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARNING]

    @property
    def notes(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == NOTE]


def _of(card: dict, key: str, kind: type):
    """``card[key]`` if it is the type the spec says, else an empty one.

    Every caller is fact extraction, which runs *after* the checks. A card that
    puts a string where an object belongs has already earned an error; what it
    must not do is stop the report being rendered at all.
    """
    value = card.get(key)
    return value if isinstance(value, kind) else kind()


def review(specimen: Specimen) -> Review:
    """Every check, over one specimen. Never raises on a malformed card."""
    peer = specimen.peer
    findings: list[Finding] = []

    if specimen.card is None:
        findings.append(
            Finding(
                peer,
                ERROR,
                "no-card",
                "no card was retrieved",
                specimen.error or specimen.parse_error or "unknown failure",
            )
        )
        return Review(peer=peer, shape=None, findings=findings, facts={})

    card = specimen.card
    shape = detect(card)
    facts: dict = {}

    findings += _check_shape(peer, card, shape)
    findings += _check_required(peer, card)
    findings += _check_extensions(peer, card)
    interfaces, interface_findings = _interfaces(peer, card, shape)
    findings += interface_findings
    findings += _check_declared_versions(peer, shape, interfaces)
    findings += _check_reachability(peer, specimen, interfaces)
    findings += _check_capabilities(peer, card)
    findings += _check_modes(peer, card)
    skills, skill_findings = _skills(peer, card)
    findings += skill_findings
    findings += _check_security(peer, specimen, card)
    findings += _check_provenance(peer, card)

    facts.update(
        {
            "shape": shape.label,
            "declared_version": shape.declared,
            "fields": sorted(card),
            "extension_fields": sorted(set(card) - KNOWN_FIELDS),
            "interfaces": interfaces,
            "transports": sorted({i["transport"] for i in interfaces if i["transport"]}),
            "interface_versions": sorted(
                {i.get("protocol_version", "") for i in interfaces if i.get("protocol_version")}
            ),
            "skill_ids": [s.get("id", "") for s in skills],
            "skill_count": len(skills),
            "tags": sorted({t for s in skills for t in _of(s, "tags", list)}),
            # `_of` throughout: the checks above already reported every
            # wrongly-typed field, and a card that earned four errors must
            # still produce facts. Duplicating the type checks here as
            # exceptions would make the *report* on a malformed card a
            # traceback -- which is the one output that helps nobody.
            "capabilities": sorted(k for k, v in _of(card, "capabilities", dict).items() if v),
            "input_modes": _of(card, "defaultInputModes", list),
            "output_modes": _of(card, "defaultOutputModes", list),
            "security_schemes": sorted(_of(card, "securitySchemes", dict)),
            "signed": bool(card.get("signatures")),
            "provider": _of(card, "provider", dict).get("organization", ""),
            "name": card.get("name", ""),
            "version": card.get("version", ""),
            "bytes": specimen.byte_count,
        }
    )

    findings.sort(key=lambda f: (f.rank, f.code))
    return Review(peer=peer, shape=shape, findings=findings, facts=facts)


def _check_shape(peer: str, card: dict, shape: Shape) -> list[Finding]:
    out = [
        Finding(
            peer,
            NOTE,
            "shape",
            f"card shape: {shape.label}",
            SHAPE_DESCRIPTIONS.get(shape.label, ""),
        )
    ]
    if shape.label == "unrecognised":
        out.append(
            Finding(
                peer,
                ERROR,
                "no-interface",
                "the card names no endpoint at all",
                "no url, preferredTransport, additionalInterfaces or "
                "supportedInterfaces: a client has nowhere to send a message",
            )
        )
    if shape.disagrees:
        out.append(
            Finding(
                peer,
                WARNING,
                "version-shape-mismatch",
                f"declares protocolVersion {shape.declared} but is shaped like {shape.label}",
                "a client that branches on the declared version will pick the "
                "wrong parser; branch on the presence of supportedInterfaces "
                "instead",
                field="protocolVersion",
            )
        )
    return out


def _check_declared_versions(
    peer: str, shape: Shape, interfaces: list[dict]
) -> list[Finding]:
    """Where the card says which protocol version it speaks -- if it says.

    There are two places, and no runtime measured so far uses both. ADK writes
    it into each ``supportedInterfaces`` entry; a2a-sdk writes it at the top
    level. A client that reads one location concludes the other's cards declare
    nothing, and a client that reads both has to decide which wins when they
    disagree -- which they do, by a whole major version, on one machine.
    """
    per_interface = sorted(
        {i["protocol_version"] for i in interfaces if i.get("protocol_version")}
    )
    out: list[Finding] = []

    if not shape.declared and not per_interface:
        out.append(
            Finding(
                peer, NOTE, "no-declared-version",
                "the card declares no protocolVersion anywhere",
                "the client has to infer the revision from the keys",
                field="protocolVersion",
            )
        )
        return out

    if not shape.declared and per_interface:
        out.append(
            Finding(
                peer, NOTE, "version-per-interface",
                f"protocolVersion is declared per interface ({', '.join(per_interface)}), "
                "not on the card",
                "a client reading only the top level sees an undeclared card",
                field="supportedInterfaces[].protocolVersion",
            )
        )
    if shape.declared and per_interface and [shape.declared] != per_interface:
        out.append(
            Finding(
                peer, WARNING, "version-declared-twice",
                f"card declares protocolVersion {shape.declared} and its interfaces "
                f"declare {', '.join(per_interface)}",
                "two declarations, two values; nothing on the card says which "
                "one a client should believe",
                field="protocolVersion",
            )
        )
    if len(per_interface) > 1:
        out.append(
            Finding(
                peer, NOTE, "mixed-interface-versions",
                f"interfaces declare more than one protocol version: "
                f"{', '.join(per_interface)}",
                field="supportedInterfaces[].protocolVersion",
            )
        )
    return out


def _check_required(peer: str, card: dict) -> list[Finding]:
    out = []
    for field in REQUIRED_CORE:
        if field not in card:
            out.append(
                Finding(
                    peer, ERROR, "missing-required", f"required field {field} is absent",
                    field=field,
                )
            )
        elif card[field] in ("", [], {}, None):
            # Present-and-empty is worse than absent: a client checking `in`
            # rather than truthiness sails past it and fails later, further
            # from the cause.
            out.append(
                Finding(
                    peer, ERROR, "empty-required", f"required field {field} is empty",
                    field=field,
                )
            )
    return out


def _check_extensions(peer: str, card: dict) -> list[Finding]:
    extra = sorted(set(card) - KNOWN_FIELDS)
    if not extra:
        return []
    return [
        Finding(
            peer,
            NOTE,
            "vendor-fields",
            f"{len(extra)} field(s) outside the spec: {', '.join(extra)}",
            "not an error -- a card is allowed to carry more than the spec "
            "names -- but no cross-vendor client will read them",
        )
    ]


def _interfaces(peer: str, card: dict, shape: Shape) -> tuple[list[dict], list[Finding]]:
    """Normalise every revision's endpoint fields into one list.

    The whole reason ``review`` exists before ``compare``: three revisions
    express "where do I send a message" three different ways, and a comparison
    that has to know that is a comparison that will get it wrong once.
    """
    out: list[dict] = []
    findings: list[Finding] = []

    for index, entry in enumerate(card.get("supportedInterfaces") or []):
        if not isinstance(entry, dict):
            findings.append(
                Finding(
                    peer, ERROR, "bad-interface",
                    f"supportedInterfaces[{index}] is not an object",
                    field=f"supportedInterfaces[{index}]",
                )
            )
            continue
        out.append(
            {
                "url": str(entry.get("url") or ""),
                "transport": str(
                    entry.get("protocolBinding") or entry.get("transport") or ""
                ),
                # Measured 2026-08-24: ADK's to_a2a() declares the protocol
                # version *here*, per interface, and nowhere else; a2a-sdk
                # declares it at the top level and not here -- with a different
                # value. A reader that looks in one place sees one of them say
                # nothing, which is why both are collected.
                "protocol_version": str(entry.get("protocolVersion") or ""),
                "source": f"supportedInterfaces[{index}]",
            }
        )
        unknown = sorted(set(entry) - INTERFACE_KNOWN)
        if unknown:
            findings.append(
                Finding(
                    peer, NOTE, "interface-extra-fields",
                    f"supportedInterfaces[{index}] carries {', '.join(unknown)}",
                    field=f"supportedInterfaces[{index}]",
                )
            )

    if url := card.get("url"):
        out.append(
            {
                "url": str(url),
                "transport": str(card.get("preferredTransport") or ""),
                "protocol_version": "",
                "source": "url",
            }
        )
    for index, entry in enumerate(card.get("additionalInterfaces") or []):
        if isinstance(entry, dict):
            out.append(
                {
                    "url": str(entry.get("url") or ""),
                    "transport": str(entry.get("transport") or entry.get("protocolBinding") or ""),
                    "protocol_version": str(entry.get("protocolVersion") or ""),
                    "source": f"additionalInterfaces[{index}]",
                }
            )

    # A hybrid card says the same thing twice, and the two copies can drift.
    if shape.current and shape.legacy:
        primary = next((i["url"] for i in out if i["source"].startswith("supportedInterfaces")), "")
        legacy = next((i["url"] for i in out if i["source"] == "url"), "")
        if primary and legacy and primary != legacy:
            findings.append(
                Finding(
                    peer, ERROR, "interface-drift",
                    "the 1.0 and pre-1.0 copies of the endpoint disagree",
                    f"supportedInterfaces[0].url={primary} but url={legacy}; "
                    "which one a client dials depends on its SDK's revision",
                    field="url",
                )
            )

    for interface in out:
        transport = interface["transport"]
        if not transport:
            findings.append(
                Finding(
                    peer, WARNING, "no-transport",
                    f"{interface['source']} names no transport",
                    "a client must guess the binding; JSONRPC is the usual "
                    "default but nothing on the card says so",
                    field=interface["source"],
                )
            )
        elif transport not in KNOWN_TRANSPORTS:
            findings.append(
                Finding(
                    peer, NOTE, "unknown-transport",
                    f"{interface['source']} advertises transport {transport!r}",
                    "outside the spec's list; either a vendor binding or a new one",
                    field=interface["source"],
                )
            )
    return out, findings


def _check_reachability(
    peer: str, specimen: Specimen, interfaces: list[dict]
) -> list[Finding]:
    """The advertised URL against the URL we actually dialled.

    This is the finding this repo was forked to chase. ADK's ``to_a2a(host,
    port)`` writes the server's *bind* address onto the card, so an agent
    behind Cloud Run advertises ``http://127.0.0.1:8080`` to the internet.
    Every client that routes by card URL -- which is most of them, correctly --
    then cannot reach an agent it just successfully discovered.
    """
    out: list[Finding] = []
    dialled = urlparse(specimen.endpoint)
    remote = dialled.hostname not in _LOOPBACK if dialled.hostname else False

    for interface in interfaces:
        url = interface["url"]
        source = interface["source"]
        if not url:
            out.append(
                Finding(
                    peer, ERROR, "empty-url", f"{source} has no url", field=source
                )
            )
            continue
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.hostname:
            out.append(
                Finding(
                    peer, ERROR, "malformed-url", f"{source} url is not absolute: {url}",
                    field=source,
                )
            )
            continue
        if remote and parsed.hostname in _LOOPBACK:
            out.append(
                Finding(
                    peer, ERROR, "bind-address-on-card",
                    f"{source} advertises a loopback address: {url}",
                    f"the card was fetched from {specimen.endpoint}, so this is "
                    "the server's bind address, not an address any client can "
                    "dial. A client that routes by card URL is unreachable to "
                    "an agent it just discovered.",
                    field=source,
                )
            )
        elif remote and parsed.hostname != dialled.hostname:
            out.append(
                Finding(
                    peer, WARNING, "url-host-differs",
                    f"{source} advertises {parsed.hostname}, card came from "
                    f"{dialled.hostname}",
                    "legitimate behind a gateway, and indistinguishable from a "
                    "stale card until someone dials it",
                    field=source,
                )
            )
        if parsed.scheme == "http" and remote:
            out.append(
                Finding(
                    peer, WARNING, "plaintext-url",
                    f"{source} advertises http:// for a remote agent: {url}",
                    field=source,
                )
            )
    return out


def _check_capabilities(peer: str, card: dict) -> list[Finding]:
    capabilities = card.get("capabilities")
    if capabilities is None:
        return []
    if not isinstance(capabilities, dict):
        return [
            Finding(
                peer, ERROR, "bad-capabilities",
                f"capabilities is a {type(capabilities).__name__}, not an object",
                field="capabilities",
            )
        ]
    unknown = sorted(set(capabilities) - CAPABILITY_KNOWN)
    out = []
    if unknown:
        out.append(
            Finding(
                peer, NOTE, "capability-extra-fields",
                f"capabilities carries {', '.join(unknown)}",
                field="capabilities",
            )
        )
    declared = sorted(k for k, v in capabilities.items() if v)
    out.append(
        Finding(
            peer, NOTE, "capabilities",
            "declares " + (", ".join(declared) if declared else "no capabilities"),
            field="capabilities",
        )
    )
    return out


def _check_modes(peer: str, card: dict) -> list[Finding]:
    out = []
    for field in ("defaultInputModes", "defaultOutputModes"):
        modes = card.get(field)
        if modes is None:
            continue
        if not isinstance(modes, list):
            out.append(
                Finding(
                    peer, ERROR, "bad-modes",
                    f"{field} is a {type(modes).__name__}, not a list",
                    field=field,
                )
            )
            continue
        # Media types with no slash are the common shape of this mistake:
        # "text" instead of "text/plain". Cheap to check, and a client that
        # negotiates on it silently matches nothing.
        malformed = [m for m in modes if isinstance(m, str) and "/" not in m]
        if malformed:
            out.append(
                Finding(
                    peer, WARNING, "non-media-type",
                    f"{field} contains {', '.join(malformed)}",
                    "not media types; content negotiation against these matches "
                    "nothing",
                    field=field,
                )
            )
    return out


def _skills(peer: str, card: dict) -> tuple[list[dict], list[Finding]]:
    raw = card.get("skills")
    if not isinstance(raw, list):
        return [], (
            []
            if raw is None
            else [
                Finding(
                    peer, ERROR, "bad-skills",
                    f"skills is a {type(raw).__name__}, not a list", field="skills"
                )
            ]
        )
    skills = [s for s in raw if isinstance(s, dict)]
    out: list[Finding] = []
    if len(skills) != len(raw):
        out.append(
            Finding(
                peer, ERROR, "bad-skill",
                f"{len(raw) - len(skills)} entry in skills is not an object",
                field="skills",
            )
        )
    if not skills:
        out.append(
            Finding(
                peer, WARNING, "no-skills",
                "the card advertises no skills",
                "discovery works and a router has nothing to route on",
                field="skills",
            )
        )

    seen: dict[str, int] = {}
    for index, skill in enumerate(skills):
        for field in SKILL_REQUIRED:
            if not skill.get(field):
                out.append(
                    Finding(
                        peer,
                        ERROR if field == "id" else WARNING,
                        "skill-missing-field",
                        f"skills[{index}] has no {field}",
                        field=f"skills[{index}].{field}",
                    )
                )
        skill_id = str(skill.get("id") or "")
        if skill_id and skill_id in seen:
            out.append(
                Finding(
                    peer, ERROR, "duplicate-skill-id",
                    f"skill id {skill_id!r} appears at indexes "
                    f"{seen[skill_id]} and {index}",
                    "a client selecting by id gets whichever its parser kept",
                    field=f"skills[{index}].id",
                )
            )
        elif skill_id:
            seen[skill_id] = index
        unknown = sorted(set(skill) - SKILL_KNOWN)
        if unknown:
            out.append(
                Finding(
                    peer, NOTE, "skill-extra-fields",
                    f"skills[{index}] carries {', '.join(unknown)}",
                    field=f"skills[{index}]",
                )
            )
        if not skill.get("examples"):
            out.append(
                Finding(
                    peer, NOTE, "skill-no-examples",
                    f"skills[{index}] gives no examples",
                    "optional, and the field a model-driven router leans on hardest",
                    field=f"skills[{index}].examples",
                )
            )
    return skills, out


def _check_security(peer: str, specimen: Specimen, card: dict) -> list[Finding]:
    """What the card says about authentication, against how it was fetched.

    The most useful cross-check in the file. These agents are reachable only
    with a federated credential -- that is the whole deployment -- and a card
    that names no security scheme is telling every client the opposite. The
    fetch knows which credential it used, so the contradiction is checkable
    rather than merely suspected.
    """
    out: list[Finding] = []
    schemes = card.get("securitySchemes") or {}
    requirements = card.get("securityRequirements") or card.get("security") or []
    authenticated = specimen.auth_used != "none"

    if authenticated and not schemes:
        out.append(
            Finding(
                peer, WARNING, "undeclared-auth",
                f"card was fetched with {specimen.auth_used} and names no securitySchemes",
                "a client reading only the card would dial this agent "
                "unauthenticated and get a 401 it cannot explain",
                field="securitySchemes",
            )
        )
    elif schemes:
        out.append(
            Finding(
                peer, NOTE, "security-schemes",
                f"declares {len(schemes)} security scheme(s): {', '.join(sorted(schemes))}",
                field="securitySchemes",
            )
        )
    if schemes and not requirements:
        out.append(
            Finding(
                peer, WARNING, "schemes-without-requirements",
                "securitySchemes are declared but nothing requires them",
                "a scheme with no requirement is documentation, not a rule",
                field="securityRequirements",
            )
        )
    if card.get("supportsAuthenticatedExtendedCard"):
        out.append(
            Finding(
                peer, NOTE, "extended-card",
                "an authenticated extended card is available",
                "this public card is not the whole card; the extended one may "
                "name skills this comparison never saw",
                field="supportsAuthenticatedExtendedCard",
            )
        )
    if not authenticated and specimen.auth_configured not in ("", "none"):
        out.append(
            Finding(
                peer, ERROR, "auth-fell-back",
                f"peer is configured for {specimen.auth_configured} but the fetch "
                "carried no credential",
                "this card is not comparable with the authenticated ones -- an "
                "open card and a privileged card can differ for reasons that "
                "have nothing to do with the runtime",
            )
        )
    return out


def _check_provenance(peer: str, card: dict) -> list[Finding]:
    out = []
    if card.get("signatures"):
        out.append(
            Finding(
                peer, NOTE, "signed", f"card carries {len(card['signatures'])} signature(s)",
                field="signatures",
            )
        )
    else:
        out.append(
            Finding(
                peer, NOTE, "unsigned", "card is unsigned",
                "nothing binds this card to the agent it claims to describe",
                field="signatures",
            )
        )
    for field in ("provider", "documentationUrl", "iconUrl"):
        if not card.get(field):
            out.append(
                Finding(
                    peer, NOTE, "absent-optional", f"no {field}", field=field
                )
            )
    return out


def review_all(specimens: list[Specimen]) -> list[Review]:
    return [review(specimen) for specimen in specimens]
