"""The two workstation credential modes.

`google-id-token` and `aws-sigv4` both start at the GCE metadata server, and a
workstation has none. These two modes exist so `agentcard fetch` can reach the
deployed mesh from a laptop -- and each of them measures something *different*
from the federated mode it stands in for. The tests that matter here are the
ones that pin that difference, not the happy paths.
"""

import json

import httpx
import pytest

from peers.auth import (
    AwsSigV4LocalAuth,
    GcloudIdentity,
    credentials_for,
)
from peers.errors import AdapterError
from peers.registry import build_peers, parse_inline

# A JWT whose payload is {"exp": 4102444800} -- 2100-01-01, so it never expires
# mid-suite. Signature is not checked by anything under test.
FAR_FUTURE_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjQxMDI0NDQ4MDB9.c2ln"


class _FakeProcess:
    def __init__(self, code: int, out: str = "", err: str = "") -> None:
        self.returncode = code
        self._out = out.encode()
        self._err = err.encode()

    async def communicate(self):
        return self._out, self._err

    def kill(self) -> None:  # pragma: no cover - only on the timeout path
        pass


def _exec_stub(monkeypatch, module, responses):
    """Answer create_subprocess_exec from a list of (matcher, _FakeProcess)."""
    calls = []

    async def fake_exec(program, *args, **kwargs):
        calls.append((program, args))
        for matcher, process in responses:
            if matcher(args):
                return process
        raise AssertionError(f"unexpected exec: {program} {args}")

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fake_exec)
    return calls


# --- gcloud-id-token -------------------------------------------------------


@pytest.mark.anyio
async def test_gcloud_pins_the_audience_when_the_account_allows_it(monkeypatch):
    from peers import auth

    calls = _exec_stub(monkeypatch, auth, [(lambda a: True, _FakeProcess(0, FAR_FUTURE_JWT))])
    token = await GcloudIdentity().id_token("https://svc.example")
    assert token == FAR_FUTURE_JWT
    assert "--audiences=https://svc.example" in calls[0][1]


@pytest.mark.anyio
async def test_gcloud_falls_back_when_a_user_account_cannot_pin_the_audience(monkeypatch, caplog):
    """The trap this mode exists to document.

    A user account is refused `--audiences`, so the token that comes back is
    audienced to gcloud's own OAuth client id -- not the service URL. Cloud Run
    accepts it by IAM role anyway. The fallback is fine; believing the audience
    condition held is not, so it must be logged.
    """
    from peers import auth

    refusal = (
        "ERROR: (gcloud.auth.print-identity-token) Invalid account type for "
        "`--audiences`. Requires valid service account."
    )
    calls = _exec_stub(
        monkeypatch,
        auth,
        [
            (lambda a: any("--audiences" in x for x in a), _FakeProcess(1, "", refusal)),
            (lambda a: True, _FakeProcess(0, FAR_FUTURE_JWT)),
        ],
    )
    with caplog.at_level("WARNING"):
        token = await GcloudIdentity().id_token("https://svc.example")

    assert token == FAR_FUTURE_JWT
    assert len(calls) == 2
    assert "--audiences=https://svc.example" not in calls[1][1]
    assert "not evidence that an audience condition holds" in caplog.text


@pytest.mark.anyio
async def test_gcloud_failure_carries_the_cli_words(monkeypatch):
    from peers import auth

    _exec_stub(
        monkeypatch,
        auth,
        [(lambda a: True, _FakeProcess(1, "", "ERROR: (gcloud.auth) not logged in"))],
    )
    with pytest.raises(AdapterError, match="not logged in"):
        await GcloudIdentity().id_token("https://svc.example")


@pytest.mark.anyio
async def test_a_missing_gcloud_names_the_way_out(monkeypatch):
    from peers import auth

    async def missing(*args, **kwargs):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(auth.asyncio, "create_subprocess_exec", missing)
    with pytest.raises(AdapterError, match="gcloud auth login"):
        await GcloudIdentity(executable="gcloud").id_token("https://svc.example")


def test_gcloud_mode_is_reported_apart_from_the_federated_one():
    """Same wire format, different principal. The report has to distinguish them."""
    peer = build_peers(parse_inline(["demo=https://x.example,auth=gcloud-id-token"]))[0]
    assert peer.resolved_auth == "gcloud-id-token"
    assert peer.keyless


# --- aws-sigv4-local -------------------------------------------------------


@pytest.mark.anyio
async def test_local_sigv4_prefers_the_environment(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "session")
    auth = AwsSigV4LocalAuth(region="us-west-2")
    credentials = await auth._credentials()
    assert credentials.access_key_id == "AKIAEXAMPLE"
    assert credentials.session_token == "session"


@pytest.mark.anyio
async def test_local_sigv4_falls_back_to_the_cli(monkeypatch):
    from peers import auth as auth_mod

    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    payload = json.dumps(
        {
            "AccessKeyId": "AKIAFROMCLI",
            "SecretAccessKey": "s",
            "SessionToken": "t",
            "Expiration": "2100-01-01T00:00:00Z",
        }
    )
    _exec_stub(monkeypatch, auth_mod, [(lambda a: True, _FakeProcess(0, payload))])
    credentials = await AwsSigV4LocalAuth(region="us-west-2")._credentials()
    assert credentials.access_key_id == "AKIAFROMCLI"


@pytest.mark.anyio
async def test_local_sigv4_signs_the_request(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    auth = AwsSigV4LocalAuth(region="us-west-2", extra_headers={"x-amzn-trace": "t"})
    request = httpx.Request("GET", "https://bedrock-agentcore.us-west-2.amazonaws.com/x")
    flow = auth.async_auth_flow(request)
    signed = await flow.__anext__()
    assert signed.headers["Authorization"].startswith("AWS4-HMAC-SHA256")
    # The extra header must fall inside the signature, not merely be present.
    assert "x-amzn-trace" in signed.headers["Authorization"]


def test_local_sigv4_does_not_claim_to_be_keyless(monkeypatch):
    """It mints nothing, so it looks keyless -- but what it reads off the disk
    is very often a static access key, and it cannot tell which it got."""
    monkeypatch.setenv("DEMO_A2A_REGION", "us-west-2")
    peer = build_peers(
        parse_inline(["demo=https://x.example,auth=aws-sigv4-local"]),
    )[0]
    assert peer.resolved_auth == "aws-sigv4-local"
    assert not peer.keyless


def test_local_sigv4_still_requires_a_region(monkeypatch):
    monkeypatch.delenv("DEMO_A2A_REGION", raising=False)
    with pytest.raises(AdapterError, match="DEMO_A2A_REGION"):
        credentials_for("demo", "https://x.example", mode="aws-sigv4-local")
