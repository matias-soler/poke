# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

`poke` is a small Python tool that drives a **LEGO Mindstorms NXT** brick over USB to physically press buttons on a device under test. A motor arm rotates a configured number of degrees to "press" a button, then rotates back to "unpress".

The user (Matias) uses this for hardware testing — exercising a physical UI repeatably from scripts.

## Architecture (adb-style)

Two binaries, one process owning the hardware:

- **`poked`** — long-running daemon. Owns the USB connection to the NXT brick. Loads `config.toml`, listens on a Unix domain socket (`~/.poke/poked.sock` or `$XDG_RUNTIME_DIR/poked.sock`). Single-user, no auth — relies on filesystem perms (0600).
- **`poke`** — thin CLI client (typer). Opens the socket, sends one JSON-line request, prints the JSON reply, exits. Examples:
  - `poke press a`
  - `poke unpress a`
  - `poke status`
  - `poke stop`
  - `poke raw-turn A 75 90`

Wire protocol: newline-delimited JSON over `AF_UNIX`. Request `{"cmd": "...", ...}`. Reply `{"ok": true|false, "result"|"error": ...}`. See `src/poke/protocol.py`.

## Layout

```
poke/
├── CLAUDE.md             # this file
├── pyproject.toml        # deps + console_scripts entry points
├── config.toml           # button → (motor, angle, power, hold)
├── udev/70-nxt.rules     # Linux: non-root USB access to the NXT
├── .gitignore
└── src/poke/
    ├── __init__.py
    ├── config.py         # tomllib loader + dataclasses
    ├── controller.py     # wraps nxt-python Motor; tracks press state
    ├── protocol.py       # JSON-line framing + default socket path
    ├── daemon.py         # `poked` entry: socket server + dispatch
    └── client.py         # `poke` entry: typer CLI
```

## Dev workflow

```bash
# Setup (once)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# macOS prereq
brew install libusb

# Linux prereq (non-root USB)
sudo cp udev/70-nxt.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules

# Run
poked --config config.toml      # in one terminal
poke status                     # in another
poke press a
poke unpress a
```

Stop the daemon with Ctrl+C; the socket file is cleaned up on exit.

## Things to verify on first hardware test

These are **assumptions I haven't confirmed against a real brick** — flag them when you do the first run:

- **nxt-python v3 API surface.** I'm calling `nxt.locator.find()`, `brick.get_motor(nxt.motor.Port.A)`, and `motor.turn(power, tacho_units, brake=...)`. Confirm signatures against the installed version (`pip show nxt-python`).
- **Power range.** Config validates `power ∈ [-100, 100]`. nxt-python may accept up to ±127; widen if needed.
- **`brake=True` semantics.** Used to implement `hold = true`. Confirm it actually holds position against back-drive on a real motor; if not, we'll need an active position controller.
- **macOS USB claim.** libusb usually grabs the NXT cleanly, but some macOS versions need `detach_kernel_driver`. If `nxt.locator.find()` raises a USBError, that's the likely cause.
- **Tachometer drift.** `motor.turn(power, +N)` then `motor.turn(-power, +N)` is *relative* — an interrupted press leaves the unpress short. If drift shows up, switch to absolute positioning anchored to a zero captured at startup.

## Conventions

- Python 3.11+ (uses stdlib `tomllib`).
- Type hints everywhere; `from __future__ import annotations` at the top of each module.
- No comments explaining *what* the code does. Only add a comment for a non-obvious *why*.
- No tests yet — add them when the hardware behavior stabilizes.
- Dependencies: `nxt-python`, `pyusb`, `typer`. Don't add more without a clear reason.

## What this project is NOT

- Not a general robotics library. It's a single-purpose button-presser.
- Not multi-user / networked. Unix socket on localhost, single operator.
- Not safety-rated. Don't use it to actuate anything where a runaway motor matters.
