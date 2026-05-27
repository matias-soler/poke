from __future__ import annotations

import os
from pathlib import Path

from poke.protocol import decode, default_socket_path, encode


def test_encode_decode_roundtrip():
    msg = {"cmd": "press", "button": "a"}
    line = encode(msg)
    assert line.endswith(b"\n")
    assert decode(line.rstrip(b"\n")) == msg


def test_default_socket_xdg(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp/xdg")
    assert default_socket_path() == Path("/tmp/xdg/poked.sock")


def test_default_socket_home(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert default_socket_path() == Path.home() / ".poke" / "poked.sock"
