"""Tests for the server entrypoint: start_server wiring, CLI arg parsing, and
TLS credential loading. No hardware — a FakeSoc stands in for the QickSoc."""

import grpc
import pytest

from conftest import FakeSoc
from qcat_grpc import server as server_mod
from qcat_grpc.client import GRPC_OPTIONS, QickSocClient


def test_start_server_with_injected_soc_serves():
    """start_server(soc=...) binds a real port and serves the FakeSoc, so a
    client can round-trip a call without any hardware or QickSoc import."""
    fake = FakeSoc(tproc_version=1)
    server, port = server_mod.start_server(host="localhost", port=0, soc=fake)
    try:
        assert port > 0
        with QickSocClient(grpc.insecure_channel(f"localhost:{port}", options=GRPC_OPTIONS)) as soc:
            assert soc.get_cfg() == fake.get_cfg()
    finally:
        server.stop(grace=None)


def test_main_parses_args_and_starts(monkeypatch):
    captured = {}

    class FakeServer:
        def wait_for_termination(self):
            captured["waited"] = True

    def fake_start_server(**kwargs):
        captured.update(kwargs)
        return FakeServer(), 8000

    monkeypatch.setattr(server_mod, "start_server", fake_start_server)
    server_mod.main(["--host", "127.0.0.1", "--port", "0", "--workers", "4", "--bitfile", "fw.bit"])

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 0
    assert captured["max_workers"] == 4
    assert captured["bitfile"] == "fw.bit"  # forwarded to the QickSoc constructor
    assert captured["server_credentials"] is None
    assert captured["waited"] is True


def test_main_tls_requires_cert_and_key_together():
    with pytest.raises(SystemExit):
        server_mod.main(["--tls-cert", "only-cert.pem"])


def test_main_builds_tls_credentials(monkeypatch, tmp_path):
    cert = tmp_path / "server.pem"
    key = tmp_path / "server.key"
    cert.write_bytes(b"CERT")
    key.write_bytes(b"KEY")

    captured = {}

    class FakeServer:
        def wait_for_termination(self):
            pass

    def fake_start_server(**kwargs):
        captured.update(kwargs)
        return FakeServer(), 8000

    monkeypatch.setattr(server_mod, "start_server", fake_start_server)
    server_mod.main(["--tls-cert", str(cert), "--tls-key", str(key)])
    assert isinstance(captured["server_credentials"], grpc.ServerCredentials)


def test_load_server_credentials_plain_and_mtls(monkeypatch, tmp_path):
    cert = tmp_path / "server.pem"
    key = tmp_path / "server.key"
    ca = tmp_path / "ca.pem"
    cert.write_bytes(b"CERT")
    key.write_bytes(b"KEY")
    ca.write_bytes(b"CA")

    calls = {}

    def fake_ssl(pairs, root_certificates, require_client_auth):
        calls["pairs"] = pairs
        calls["root"] = root_certificates
        calls["require"] = require_client_auth
        return "creds"

    monkeypatch.setattr(server_mod.grpc, "ssl_server_credentials", fake_ssl)

    # no CA => TLS only, no client auth required
    server_mod.load_server_credentials(str(cert), str(key))
    assert calls["pairs"] == [(b"KEY", b"CERT")]
    assert calls["root"] is None and calls["require"] is False

    # CA given => mTLS, client auth required
    server_mod.load_server_credentials(str(cert), str(key), str(ca))
    assert calls["root"] == b"CA" and calls["require"] is True
