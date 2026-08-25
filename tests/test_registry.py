"""The peer registry: built-ins, files, inline flags, and what each refuses."""

import pytest

from peers.errors import AdapterError
from peers.registry import (
    BUILTIN_PEERS,
    build_peers,
    builtin_specs,
    load_specs,
    parse_inline,
)


def test_builtins_default_to_the_local_specimen_ports():
    specs = builtin_specs()
    assert [s.name for s in specs] == list(BUILTIN_PEERS)
    # 11xxx, not the research mesh's 10xxx. See the comment in registry.py:
    # sharing the range silently compared the wrong agents once already.
    assert all(":110" in s.endpoint for s in specs)


def test_builtins_follow_their_environment_variable(monkeypatch):
    monkeypatch.setenv("AWS_A2A_ENDPOINT", "https://agentcore.example/invocations/")
    assert builtin_specs(["aws"])[0].endpoint == "https://agentcore.example/invocations/"


def test_an_unknown_builtin_is_refused():
    with pytest.raises(ValueError, match="unknown built-in"):
        builtin_specs(["oracle"])


def test_a_peers_file_is_read(tmp_path):
    path = tmp_path / "peers.toml"
    path.write_text(
        """
[[peer]]
name = "gcp"
endpoint = "https://research-gcp.example"
runtime = "Cloud Run / ADK to_a2a"
auth = "google-id-token"

[[peer]]
name = "public"
endpoint = "https://example.org/agent"
tags = ["third-party"]
"""
    )
    specs = load_specs(path)
    assert [s.name for s in specs] == ["gcp", "public"]
    assert specs[0].auth == "google-id-token"
    assert specs[1].auth is None
    assert specs[1].tags == ("third-party",)


def test_a_duplicate_peer_name_is_refused(tmp_path):
    """Silently overwriting would show one row where two were asked for."""
    path = tmp_path / "peers.toml"
    path.write_text(
        '[[peer]]\nname="a"\nendpoint="https://a"\n[[peer]]\nname="a"\nendpoint="https://b"\n'
    )
    with pytest.raises(AdapterError, match="duplicate peer name"):
        load_specs(path)


def test_an_unknown_auth_mode_is_refused_at_read_time(tmp_path):
    path = tmp_path / "peers.toml"
    path.write_text('[[peer]]\nname="a"\nendpoint="https://a"\nauth="magic"\n')
    with pytest.raises(AdapterError, match="unknown auth"):
        load_specs(path)


def test_an_entry_missing_an_endpoint_is_refused(tmp_path):
    path = tmp_path / "peers.toml"
    path.write_text('[[peer]]\nname="a"\n')
    with pytest.raises(AdapterError, match="needs both name and endpoint"):
        load_specs(path)


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(AdapterError, match="not found"):
        load_specs(tmp_path / "absent.toml")


def test_inline_peers_parse_their_options():
    specs = parse_inline(["demo=https://x.example,auth=none,runtime=Foundry"])
    assert specs[0].name == "demo"
    assert specs[0].endpoint == "https://x.example"
    assert specs[0].runtime == "Foundry"


def test_an_inline_peer_without_a_url_is_refused():
    with pytest.raises(AdapterError, match="wants name=URL"):
        parse_inline(["demo"])


def test_an_explicit_mode_beats_the_environment(monkeypatch):
    """Two peers can want the same mode with different parameters, and there
    is only one GCP_A2A_AUTH."""
    monkeypatch.setenv("DEMO_A2A_AUTH", "google-id-token")
    specs = parse_inline(["demo=https://x.example,auth=none"])
    assert build_peers(specs)[0].credential is None


def test_the_environment_still_configures_a_peer_that_names_no_mode(monkeypatch):
    monkeypatch.setenv("DEMO_A2A_AUTH", "google-id-token")
    peer = build_peers(parse_inline(["demo=https://x.example"]))[0]
    assert peer.resolved_auth == "google-id-token"
    assert peer.keyless


def test_a_peer_with_no_credential_reports_none():
    peer = build_peers(parse_inline(["demo=https://x.example,auth=none"]))[0]
    assert peer.resolved_auth == "none"
    assert peer.keyless


def test_a_credential_that_cannot_be_minted_fails_while_assembling(monkeypatch):
    """Not halfway through the fan-out, where it looks like the remote is down."""
    monkeypatch.setenv("DEMO_A2A_AUTH", "aws-sigv4")
    monkeypatch.delenv("DEMO_A2A_ROLE_ARN", raising=False)
    with pytest.raises(AdapterError, match="DEMO_A2A_ROLE_ARN"):
        build_peers(parse_inline(["demo=https://x.example"]))
