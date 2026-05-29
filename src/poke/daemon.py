from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading
from pathlib import Path

from poke.config import Config
from poke.controller import Controller
from poke.protocol import decode, default_socket_path, encode


def _dispatch(controller: Controller, req: dict) -> dict:
    cmd = req.get("cmd")
    if cmd == "press":
        return {"ok": True, "result": controller.press(req["button"], req.get("hold_secs"))}
    if cmd == "status":
        return {"ok": True, "result": controller.status()}
    if cmd == "stop":
        return {"ok": True, "result": controller.stop_all()}
    if cmd == "raw_turn":
        return {
            "ok": True,
            "result": controller.raw_turn(req["motor"], int(req["power"]), int(req["degrees"])),
        }
    raise ValueError(f"unknown cmd {cmd!r}")


def _handle_client(conn: socket.socket, controller: Controller) -> None:
    with conn:
        buf = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line:
                    continue
                try:
                    resp = _dispatch(controller, decode(line))
                except Exception as e:
                    resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                conn.sendall(encode(resp))


def serve(config_path: Path, socket_path: Path) -> None:
    config = Config.load(config_path)
    controller = Controller(config, config_path=config_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    srv.listen(8)
    print(f"poked listening on {socket_path}", file=sys.stderr)

    # SIGTERM doesn't raise KeyboardInterrupt by default; route it through the
    # same handler as Ctrl+C so the finally block cleans up the socket file.
    signal.signal(signal.SIGTERM, signal.default_int_handler)

    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=_handle_client, args=(conn, controller), daemon=True).start()
    except KeyboardInterrupt:
        print("poked: shutting down", file=sys.stderr)
    finally:
        srv.close()
        controller.close()
        if socket_path.exists():
            socket_path.unlink()


def main() -> None:
    p = argparse.ArgumentParser(prog="poked")
    p.add_argument("--config", type=Path, default=Path("config.toml"))
    p.add_argument("--socket", type=Path, default=default_socket_path())
    args = p.parse_args()
    serve(args.config, args.socket)


if __name__ == "__main__":
    main()
