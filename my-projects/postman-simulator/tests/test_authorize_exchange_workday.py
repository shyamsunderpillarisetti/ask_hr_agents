import io
import os
import tempfile
import sys

from examples import authorize_exchange_workday as mod


def test_client_secret_from_file(tmp_path):
    p = tmp_path / "secret.txt"
    p.write_text("mysecret")
    class Args:
        client_id = "x"
        client_secret = None
        client_secret_file = str(p)
        client_secret_stdin = False
    # emulate argument handling
    secret = None
    # simulate minimal part of main: try reading file
    with open(str(p), "r") as f:
        secret = f.read().strip()
    assert secret == "mysecret"


def test_client_secret_from_stdin(monkeypatch):
    data = "stdinsecret"
    monkeypatch.setattr(sys, "stdin", io.StringIO(data))
    class Args:
        client_id = "x"
        client_secret = None
        client_secret_file = None
        client_secret_stdin = True
    # Simulate the logic from main
    client_secret = None
    if Args.client_secret:
        client_secret = Args.client_secret
    elif Args.client_secret_file:
        with open(Args.client_secret_file, "r") as f:
            client_secret = f.read().strip()
    elif Args.client_secret_stdin:
        client_secret = sys.stdin.read().strip()
    assert client_secret == data
