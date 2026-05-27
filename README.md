# poke

A tiny tool that drives a **LEGO Mindstorms NXT** brick over USB to physically
press buttons on a device under test. A motor arm rotates a configured number
of degrees to "press", then rotates back to "unpress" — useful for exercising
real hardware UIs from scripts.

## Architecture

Split adb-style: one long-running daemon owns the USB connection, and a thin
CLI client speaks to it over a Unix domain socket.

- **`poked`** — daemon. Loads `config.toml`, opens the brick, listens on
  `$XDG_RUNTIME_DIR/poked.sock` (or `~/.poke/poked.sock`). Single-user, no
  auth — relies on filesystem perms (0600).
- **`poke`** — typer CLI client. Sends one JSON-line request, prints the JSON
  reply, exits.
- **`poke.sh`** — wrapper that auto-starts the daemon when needed, with
  `start-server` / `kill-server` / `restart-server` / `server-status`.

Wire protocol: newline-delimited JSON over `AF_UNIX`. See `src/poke/protocol.py`.

## Setup

```bash
# macOS prereq
brew install libusb

# Linux prereq (non-root USB access to the NXT)
sudo cp udev/70-nxt.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules

# Install
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
```

## Usage

```bash
# adb-style wrapper (auto-starts poked if not running)
./poke.sh press a
./poke.sh unpress a
./poke.sh status
./poke.sh raw-turn A 75 90

# Server control
./poke.sh start-server
./poke.sh kill-server
./poke.sh restart-server
./poke.sh server-status
```

Or use the raw binaries directly:

```bash
.venv/bin/poked --config config.toml    # in one terminal
.venv/bin/poke press a                  # in another
```

### Config

`config.toml` maps button names to motor parameters:

```toml
[buttons.a]
motor = "A"      # NXT output port: A | B | C
angle = 90       # degrees to rotate on press; unpress rotates back the same
power = 75       # drive power, -100..100; sign sets press direction
hold = true      # brake-hold position until unpress, vs. coast
```

## Tests

```bash
# Unit tests (no hardware needed — use FakeBrick / FakeMotor)
.venv/bin/pytest

# Hardware smoke test (requires a real brick on USB)
POKE_HARDWARE=1 .venv/bin/pytest tests/test_hardware.py
```

## macOS note

`nxt.locator.find()` calls `dev.reset()` before `set_configuration()` on
non-Windows platforms. On macOS the reset re-enumerates the brick at a new
USB address, leaving the cached handle stale (`USBError: [Errno 19] No such
device`). `poke.controller.find_brick()` works around this by replicating the
USB backend's connect path minus the reset, on Darwin only.

## Layout

```
poke/
├── config.toml           # button -> (motor, angle, power, hold)
├── poke.sh               # adb-style wrapper
├── udev/70-nxt.rules     # Linux: non-root USB access
├── src/poke/
│   ├── config.py         # tomllib loader + dataclasses
│   ├── controller.py     # NXT motor wrapper, press state, USB workaround
│   ├── protocol.py       # JSON-line framing + default socket path
│   ├── daemon.py         # poked: socket server + dispatch
│   └── client.py         # poke: typer CLI
└── tests/                # pytest unit + opt-in hardware tests
```

## What this is not

- Not a general robotics library. Single-purpose button-presser.
- Not multi-user / networked. Unix socket on localhost, single operator.
- Not safety-rated. Don't use it to actuate anything where a runaway motor
  matters.
