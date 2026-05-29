from __future__ import annotations

import json
import socket
from pathlib import Path

import typer

from poke.protocol import decode, default_socket_path, encode

app = typer.Typer(help="Control the poke daemon (poked) over its local socket.")

SocketOpt = typer.Option(None, "--socket", help="Daemon socket path. Defaults to ~/.poke/poked.sock.")


def _resolve_socket(socket_path: Path | None) -> Path:
    return socket_path if socket_path is not None else default_socket_path()


def _send(req: dict, socket_path: Path) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(str(socket_path))
    except (FileNotFoundError, ConnectionRefusedError) as e:
        typer.echo(f"poked not reachable at {socket_path}: {e}", err=True)
        raise typer.Exit(2)
    try:
        s.sendall(encode(req))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    if not buf:
        typer.echo("poked closed connection without responding", err=True)
        raise typer.Exit(2)
    return decode(buf.split(b"\n", 1)[0])


def _print(resp: dict) -> None:
    typer.echo(json.dumps(resp, indent=2))
    if not resp.get("ok"):
        raise typer.Exit(1)


@app.command(context_settings={"ignore_unknown_options": True})
def press(args: list[str] = typer.Argument(None, metavar="BUTTONS [hold SECONDS]"), socket: Path = SocketOpt) -> None:
    """Momentary press: drive forward, hold, then release (spring returns the arm).

    Combine button names to act together (e.g. 'ab'). Append 'hold N' to keep the
    button(s) down N seconds before releasing, e.g. 'press ab hold 5'.
    """
    if not args:
        typer.echo("usage: poke press BUTTONS [hold SECONDS]", err=True)
        raise typer.Exit(2)
    buttons = args[0]
    rest = args[1:]
    req: dict = {"cmd": "press", "button": buttons}
    if rest:
        if len(rest) == 2 and rest[0] == "hold":
            try:
                req["hold_secs"] = float(rest[1])
            except ValueError:
                typer.echo(f"hold seconds must be a number, got {rest[1]!r}", err=True)
                raise typer.Exit(2)
        else:
            typer.echo("usage: poke press BUTTONS [hold SECONDS]", err=True)
            raise typer.Exit(2)
    _print(_send(req, _resolve_socket(socket)))


@app.command()
def status(socket: Path = SocketOpt) -> None:
    """Show per-button config."""
    _print(_send({"cmd": "status"}, _resolve_socket(socket)))


@app.command()
def stop(socket: Path = SocketOpt) -> None:
    """Emergency-stop all motors and clear pressed state."""
    _print(_send({"cmd": "stop"}, _resolve_socket(socket)))


@app.command("raw-turn", context_settings={"ignore_unknown_options": True})
def raw_turn(motor: str, power: int, degrees: int, socket: Path = SocketOpt) -> None:
    """Bypass config: turn MOTOR (A/B/C) at POWER (-100..100) by DEGREES.

    POWER may be negative to reverse direction (e.g. ``raw-turn A -55 20``).
    """
    _print(
        _send(
            {"cmd": "raw_turn", "motor": motor, "power": power, "degrees": degrees},
            _resolve_socket(socket),
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
