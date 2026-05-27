from __future__ import annotations

import json
import os
from pathlib import Path


def default_socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "poked.sock"
    return Path.home() / ".poke" / "poked.sock"


def encode(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


def decode(line: bytes) -> dict:
    return json.loads(line.decode("utf-8"))
