"""Get the card, over the same credential the calls would use.

Two decisions here are load-bearing and both were paid for in the mesh this
forked from.

**The credential goes on the client, not on a request.** Discovery is
privileged separately from invocation on all three clouds -- on AWS it is
literally a different IAM action, ``bedrock-agentcore:GetAgentCard`` -- so a
card fetch that carries no credential 403s while the call it was preparing for
would have succeeded. That failure surfaces as a transport or protocol error,
nowhere near auth, and it took a day to name the first time.

**Every candidate path is tried and every attempt is kept.** The spec moved the
card from ``/.well-known/agent.json`` to ``/.well-known/agent-card.json``, and
runtimes moved at different times. Trying only the current path and reporting
"no card" would file a *protocol revision* -- the single most interesting thing
a fetch can discover here -- as an outage.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

import httpx

from cards.model import Attempt, Corpus, Specimen
from peers import trace
from peers.auth import is_keyless
from peers.errors import AdapterError, FailureKind
from peers.registry import DEFAULT_TIMEOUT_SECONDS, Peer

log = logging.getLogger("cards.fetch")

#: Candidate discovery paths, in the order they are tried.
#:
#: ``agent-card.json`` is the current spelling and goes first so a conforming
#: runtime costs exactly one request. ``agent.json`` is the 0.2.x spelling that
#: older ADK builds still serve. Nothing else is guessed: a path this repo
#: invented would produce a 404 that means nothing, and four meaningless 404s
#: per peer would bury the one that means something.
CARD_PATHS: tuple[str, ...] = (
    "/.well-known/agent-card.json",
    "/.well-known/agent.json",
)

#: Statuses that end the search rather than moving to the next path. A 404 says
#: "not here, try elsewhere"; a 401 or 403 says "here, and you may not" -- and
#: walking on to the next path after one would turn a clean auth finding into a
#: list of denials with the real cause at the top and the report reading from
#: the bottom.
_TERMINAL_STATUSES = frozenset({401, 403})


async def fetch_card(
    peer: Peer,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    paths: tuple[str, ...] = CARD_PATHS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Specimen:
    """Fetch one peer's card. Never raises: a failure is a specimen too.

    ``transport`` is for the tests, and it is the reason every check in this
    file can be exercised against a 403 with a real AWS body, a 200 carrying
    HTML, and a card served only on the 0.2 path -- none of which can be
    arranged against a live cloud on demand.
    """
    candidates = tuple(dict.fromkeys((*peer.card_paths, *paths)))
    # So a non-standard path is traced as discovery rather than as an invoke.
    # This repo never invokes anything, so an `invoke` row in a phase breakdown
    # would be a round trip that cannot exist.
    for path in peer.card_paths:
        trace.register_card_path(path)
    specimen = Specimen(
        peer=peer.name,
        endpoint=peer.endpoint,
        runtime=peer.runtime,
        auth_configured=peer.auth or "none",
        auth_used=peer.resolved_auth,
        keyless=is_keyless(peer.resolved_auth),
        fetched_at=datetime.now(UTC),
    )

    with trace.collect() as leg:
        try:
            async with asyncio.timeout(timeout_seconds):
                await _try_paths(peer, candidates, timeout_seconds, specimen, transport)
        except TimeoutError:
            specimen.failure_kind = FailureKind.TIMEOUT.value
            specimen.error = f"discovery exceeded {timeout_seconds}s"
        except AdapterError as exc:
            specimen.failure_kind = exc.kind.value
            specimen.error = exc.safe_message()
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            specimen.failure_kind = FailureKind.PROTOCOL.value
            specimen.error = f"{type(exc).__name__}: {exc}"
        finally:
            # In a `finally` because the success path returns from inside the
            # `try` in `_try_paths`, and a trace lost on success is a trace that
            # only ever appears on failures -- which is how you end up unable to
            # say what a *working* leg costs.
            specimen.trace = list(leg.steps)

    if specimen.card is None and not specimen.error:
        tried = ", ".join(a.path for a in specimen.attempts)
        last = next((a for a in reversed(specimen.attempts) if a.status), None)
        specimen.failure_kind = (
            FailureKind.AUTHENTICATION.value
            if last is not None and last.status in _TERMINAL_STATUSES
            else FailureKind.PROTOCOL.value
        )
        specimen.error = f"no agent card served on any of: {tried}"
    for step in specimen.trace:
        log.info(
            "peer %s %s %s %s%s -> %s in %.0fms%s",
            peer.name,
            step.phase,
            step.method,
            step.host,
            step.path,
            step.status if step.status is not None else "-",
            step.elapsed_ms,
            f" [{step.request_id}]" if step.request_id else "",
        )
    return specimen


async def _try_paths(
    peer: Peer,
    candidates: tuple[str, ...],
    timeout_seconds: float,
    specimen: Specimen,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    # `local_address` pins the socket to IPv4; IPv6 to some hosts hangs in some
    # sandboxes. Carried over from the mesh's client, where it was found the
    # hard way.
    transport = transport or httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        auth=peer.credential,
        event_hooks=trace.EVENT_HOOKS,
        transport=transport,
        follow_redirects=True,
    ) as client:
        for path in candidates:
            url = f"{peer.endpoint}/{path.lstrip('/')}"
            attempt = Attempt(path=path, url=url)
            started = perf_counter()
            try:
                response = await client.get(url)
            except httpx.TimeoutException as exc:
                attempt.detail = f"timed out: {exc}"
            except (httpx.TransportError, OSError) as exc:
                attempt.detail = f"cannot reach {url}: {exc}"
            else:
                attempt.status = response.status_code
                attempt.content_type = response.headers.get("content-type", "")
                attempt.request_id = _request_id(response)
                body = response.text
                attempt.bytes = len(body.encode())
                if response.is_success:
                    attempt.ok = True
                    _record_body(specimen, attempt, body)
                else:
                    # The provider's own words, not a status line. AWS says
                    # "signature we calculated does not match" for a signing
                    # bug and "not authorized to perform" for a policy bug --
                    # the same 403, opposite afternoons.
                    attempt.detail = body.strip()[:600]
            attempt.elapsed_ms = (perf_counter() - started) * 1000
            specimen.attempts.append(attempt)

            if attempt.ok:
                specimen.path = path
                specimen.url = url
                specimen.status = attempt.status
                specimen.elapsed_ms = attempt.elapsed_ms
                specimen.content_type = attempt.content_type
                specimen.request_id = attempt.request_id
                return
            if attempt.status in _TERMINAL_STATUSES:
                specimen.status = attempt.status
                specimen.url = url
                specimen.request_id = attempt.request_id
                specimen.failure_kind = FailureKind.AUTHENTICATION.value
                specimen.error = (
                    f"{attempt.status} on {path}"
                    + (f": {attempt.detail}" if attempt.detail else "")
                )
                log.error("peer %s discovery denied: %s", peer.name, specimen.error)
                return


def _record_body(specimen: Specimen, attempt: Attempt, body: str) -> None:
    """Keep the bytes; parse them separately and survive failing to.

    A 200 carrying HTML -- a login page, a proxy's error, a runtime that routes
    unknown paths to its own index -- is the failure most likely to be read as
    success, because every status check passes. Storing the raw body means the
    report can show what actually arrived instead of "invalid card".
    """
    specimen.raw = body
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        specimen.parse_error = f"body is not JSON: {exc}"
        attempt.ok = False
        attempt.detail = specimen.parse_error
        return
    if not isinstance(parsed, dict):
        specimen.parse_error = (
            f"body is JSON but a {type(parsed).__name__}, not an object"
        )
        attempt.ok = False
        attempt.detail = specimen.parse_error
        return
    specimen.card = parsed


def _request_id(response: httpx.Response) -> str:
    for header in (
        "x-amzn-requestid",
        "x-amzn-request-id",
        "x-amz-request-id",
        "x-ms-request-id",
        "x-ms-correlation-request-id",
        "x-goog-request-id",
        "x-request-id",
        "x-cloud-trace-context",
    ):
        if value := response.headers.get(header):
            return value
    return ""


async def fetch_all(
    peers: list[Peer],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    paths: tuple[str, ...] = CARD_PATHS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Corpus:
    """Fetch every peer's card concurrently, into one corpus.

    Concurrently and independently: one peer denying discovery degrades the run
    to the remaining peers rather than failing it, which is the same property
    the mesh had and for the same reason -- the comparison is still worth
    reading with a hole in it, and the hole is itself a row.
    """
    started_at = datetime.now(UTC)
    started = perf_counter()
    specimens = await asyncio.gather(
        *(
            fetch_card(
                peer,
                timeout_seconds=timeout_seconds,
                paths=paths,
                transport=transport,
            )
            for peer in peers
        )
    )
    return Corpus(
        run_id=uuid4().hex[:12],
        started_at=started_at,
        elapsed_ms=(perf_counter() - started) * 1000,
        specimens=list(specimens),
    )
