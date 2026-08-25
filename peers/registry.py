"""Who to fetch a card from, and how to prove who is asking.

The mesh this forked from had exactly three peers, hardcoded, because it was
demonstrating that three specific clouds could be reached at all. The question
here is narrower and wider at once: narrower because nothing is invoked, only
discovered; wider because a card is worth comparing against *any* card, and a
fourth specimen -- a public A2A agent, a colleague's dev box, the same runtime
a release apart -- must not require editing code.

So a peer is data. The three deployed clouds are preloaded with the environment
variables they already use, and everything else comes from a peers file or the
command line.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from peers.auth import AUTH_MODES, auth_mode, credentials_for, is_keyless
from peers.errors import AdapterError, FailureKind

#: The three legs that already exist, and the environment variable that points
#: at each. Kept as *defaults*, not as the peer set: a run against nothing but
#: two public agents is a legitimate run.
#:
#: The local defaults are 11001-11003 rather than the research mesh's
#: 10001-10003, and that is not cosmetic. This repo was forked from a project
#: that runs three agents on those ports, and on 2026-08-24 the fork's own
#: specimens silently failed to bind while `run_mesh.sh` reported all three
#: ready -- because its health check reached the *other* repo's agents. The
#: first card comparison this tool ever produced was of the wrong mesh, and
#: nothing in the output could have said so. Two projects, two port ranges.
BUILTIN_PEERS: dict[str, tuple[str, str, str]] = {
    #  name          env var             local default              runtime label
    "gcp": ("GCP_A2A_ENDPOINT", "http://127.0.0.1:11001", "Cloud Run / ADK to_a2a"),
    "aws": ("AWS_A2A_ENDPOINT", "http://127.0.0.1:11002", "Bedrock AgentCore"),
    "azure": ("AZURE_A2A_ENDPOINT", "http://127.0.0.1:11003", "Container Apps"),
}

DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class Peer:
    """One agent to fetch a card from.

    ``auth`` is the *configured* mode; ``credential`` is the object that will
    sign the fetch, and ``resolved_auth`` is what that object says it is. They
    are reported separately on purpose. A peer configured for ``entra-fic``
    whose credential came back ``none`` did not fail -- it silently fetched an
    open card, and a comparison that cannot see that is comparing an
    authenticated card with an unauthenticated one and calling them peers.
    """

    name: str
    endpoint: str
    #: Free text: which runtime serves this, for the report's row label. Never
    #: inferred from the URL -- an inference that is right four times and wrong
    #: once is worse than a blank.
    runtime: str = ""
    auth: str = ""
    credential: httpx.Auth | None = None
    #: Extra discovery paths to try for this peer, ahead of the standard ones.
    card_paths: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @property
    def resolved_auth(self) -> str:
        return auth_mode(self.credential)

    @property
    def keyless(self) -> bool:
        return is_keyless(self.resolved_auth)

    def __str__(self) -> str:
        return self.name


@dataclass
class PeerSpec:
    """A peer before its credential has been minted. What a config file holds."""

    name: str
    endpoint: str
    runtime: str = ""
    auth: str | None = None
    card_paths: tuple[str, ...] = ()
    tags: tuple[str, ...] = field(default_factory=tuple)


def builtin_specs(names: list[str] | None = None) -> list[PeerSpec]:
    """The three deployed legs, pointed wherever their environment says."""
    selected = names or list(BUILTIN_PEERS)
    unknown = [n for n in selected if n not in BUILTIN_PEERS]
    if unknown:
        raise ValueError(f"unknown built-in peer(s): {', '.join(unknown)}")
    specs = []
    for name in selected:
        env_var, default, runtime = BUILTIN_PEERS[name]
        specs.append(
            PeerSpec(
                name=name,
                endpoint=os.getenv(env_var, default),
                runtime=runtime,
                # None, so credentials_for falls back to <NAME>_A2A_AUTH and the
                # existing deployment configuration keeps working untouched.
                auth=None,
                tags=("builtin",),
            )
        )
    return specs


def load_specs(path: str | Path) -> list[PeerSpec]:
    """Read a peers file.

    TOML, because it is in the standard library and a peers file is edited by
    hand::

        [[peer]]
        name = "gcp"
        endpoint = "https://research-gcp-xxxx-uc.a.run.app"
        runtime = "Cloud Run / ADK to_a2a"
        auth = "google-id-token"

        [[peer]]
        name = "public-demo"
        endpoint = "https://example.org/agent"
        auth = "none"
    """
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError as exc:
        raise AdapterError(
            FailureKind.VALIDATION, f"peers file not found: {path}"
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise AdapterError(
            FailureKind.VALIDATION, f"peers file {path} is not valid TOML: {exc}"
        ) from exc

    entries = data.get("peer") or []
    if not isinstance(entries, list) or not entries:
        raise AdapterError(
            FailureKind.VALIDATION,
            f"peers file {path} defines no [[peer]] entries",
        )

    specs: list[PeerSpec] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        name = str(entry.get("name") or "").strip()
        endpoint = str(entry.get("endpoint") or "").strip()
        if not name or not endpoint:
            raise AdapterError(
                FailureKind.VALIDATION,
                f"peers file {path}: entry {index + 1} needs both name and endpoint",
            )
        # Duplicate names silently overwrite each other in every dict this
        # feeds, and the report would then show one peer where two were asked
        # for -- a missing row that looks like a peer that did not answer.
        if name in seen:
            raise AdapterError(
                FailureKind.VALIDATION, f"peers file {path}: duplicate peer name {name!r}"
            )
        seen.add(name)
        auth = entry.get("auth")
        if auth is not None and str(auth).strip().lower() not in AUTH_MODES:
            raise AdapterError(
                FailureKind.VALIDATION,
                f"peers file {path}: peer {name!r} has unknown auth "
                f"{auth!r} (expected one of {AUTH_MODES})",
            )
        specs.append(
            PeerSpec(
                name=name,
                endpoint=endpoint,
                runtime=str(entry.get("runtime") or ""),
                auth=str(auth).strip().lower() if auth is not None else None,
                card_paths=tuple(entry.get("card_paths") or ()),
                tags=tuple(str(t) for t in entry.get("tags") or ()),
            )
        )
    return specs


def parse_inline(values: list[str]) -> list[PeerSpec]:
    """``--peer name=https://host[,auth=mode][,runtime=text]`` from the CLI."""
    specs: list[PeerSpec] = []
    for value in values:
        name, _, rest = value.partition("=")
        if not name.strip() or not rest.strip():
            raise AdapterError(
                FailureKind.VALIDATION,
                f"--peer wants name=URL, got {value!r}",
            )
        parts = rest.split(",")
        endpoint = parts[0].strip()
        options: dict[str, str] = {}
        for part in parts[1:]:
            key, _, val = part.partition("=")
            options[key.strip().lower()] = val.strip()
        auth = options.get("auth")
        if auth is not None and auth.lower() not in AUTH_MODES:
            raise AdapterError(
                FailureKind.VALIDATION,
                f"--peer {name}: unknown auth {auth!r} (expected one of {AUTH_MODES})",
            )
        specs.append(
            PeerSpec(
                name=name.strip(),
                endpoint=endpoint,
                runtime=options.get("runtime", ""),
                auth=auth.lower() if auth else None,
                tags=("inline",),
            )
        )
    return specs


def build_peers(specs: list[PeerSpec]) -> list[Peer]:
    """Mint each peer's credential now, not at fetch time.

    A credential that cannot be minted should fail while the peer list is being
    assembled -- named, with the provider's own words -- rather than halfway
    through a concurrent fan-out where it is indistinguishable from the remote
    being down. That distinction was expensive to recover in the mesh and it is
    free to preserve here.
    """
    peers: list[Peer] = []
    for spec in specs:
        credential = credentials_for(spec.name, spec.endpoint, mode=spec.auth)
        peers.append(
            Peer(
                name=spec.name,
                endpoint=spec.endpoint.rstrip("/"),
                runtime=spec.runtime,
                auth=spec.auth or os.getenv(f"{spec.name.upper()}_A2A_AUTH", "none"),
                credential=credential,
                card_paths=tuple(spec.card_paths),
                tags=tuple(spec.tags),
            )
        )
    return peers


__all__ = [
    "BUILTIN_PEERS",
    "DEFAULT_TIMEOUT_SECONDS",
    "Peer",
    "PeerSpec",
    "build_peers",
    "builtin_specs",
    "load_specs",
    "parse_inline",
]
