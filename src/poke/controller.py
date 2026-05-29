from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import nxt.brick
import nxt.locator
import nxt.motor
import usb.util
from nxt.backend.usb import USBSock
from usb.core import USBError

from poke.config import ButtonConfig, Config

_RECONNECT_ATTEMPTS = 5
_RECONNECT_DELAY_S = 0.3

# press brakes at the target (arresting coast/spring-back), holds the button down
# for this long, then idles so the spring returns the arm. `press <btn> hold N`
# overrides it to hold N seconds.
_DEFAULT_HOLD_S = 0.2


def find_brick():
    """Find an NXT brick over USB.

    On Darwin, ``nxt.locator.find()`` triggers ``dev.reset()`` (see
    nxt/backend/usb.py), which re-enumerates the brick at a new bus address and
    leaves the cached handle pointing at the old one — every ``set_configuration``
    then fails with ENODEV. We replicate the USB backend's connect path here,
    minus the reset, when running on macOS.
    """
    if sys.platform != "darwin":
        return nxt.locator.find()

    import usb.core

    dev = usb.core.find(idVendor=0x0694, idProduct=0x0002)
    if dev is None:
        raise RuntimeError(
            "no NXT brick found on USB — is it powered on and the cable connected? "
            "(looking for vendor 0x0694, product 0x0002)"
        )
    sock = USBSock(dev)
    dev.set_configuration()
    intf = dev.get_active_configuration()[(0, 0)]
    sock._epout, sock._epin = intf
    return nxt.brick.Brick(sock)


class Controller:
    """Owns the NXT brick connection.

    Stateless about position: ``press`` is a momentary actuation (drive forward,
    briefly hold, then release) — there is no held state to track.
    """

    def __init__(self, config: Config, brick: object | None = None, config_path: Path | None = None):
        self.config = config
        self._config_path = config_path
        self._owns_connection = brick is None
        self._lock = threading.Lock()
        if brick is not None:
            self.brick = brick
            self._motors = self._acquire_motors()
            return
        # We own the connection: try to connect, but start gracefully if the brick
        # isn't present yet (e.g. powered off). Commands reconnect on demand (see
        # _run_motor / _run_action), so the daemon stays up and recovers once the
        # brick is powered on, instead of crashing at startup with a traceback.
        self.brick = None
        self._motors = {}
        try:
            self._reconnect()
        except Exception as e:
            print(f"poked: starting without a brick ({e}); will connect on demand", file=sys.stderr)

    def _refresh_config(self) -> None:
        """Re-read config from disk so edits take effect without a daemon restart.

        Only the config-using actions call this; ``raw_turn``/``stop_all`` skip it
        so they keep working as recovery tools even while the file is being edited.
        """
        if self._config_path is not None:
            self.config = Config.load(self._config_path)

    def _acquire_motors(self) -> dict:
        return {
            "A": self.brick.get_motor(nxt.motor.Port.A),
            "B": self.brick.get_motor(nxt.motor.Port.B),
            "C": self.brick.get_motor(nxt.motor.Port.C),
        }

    def _release_brick(self) -> None:
        """Drop the current handle and free its libusb resources.

        ``Brick.close()`` only nulls Python references; it does not release the
        kernel/libusb interface claim. Without ``dispose_resources`` the device
        stays claimed by this process, so re-configuring the same device in
        ``find_brick()`` fails with EACCES. We clear ``brick``/``_motors`` up
        front so a failed reconnect can never leave motors pointing at a
        half-closed handle (which would raise AttributeError on the next call).
        """
        brick = self.brick
        self.brick = None
        self._motors = {}
        if brick is None:
            return
        dev = getattr(getattr(brick, "_sock", None), "_dev", None)
        try:
            brick.close()
        except Exception:
            pass
        if dev is not None:
            try:
                usb.util.dispose_resources(dev)
            except Exception:
                pass

    def _reconnect(self) -> None:
        self._release_brick()
        last_err: Exception | None = None
        for _ in range(_RECONNECT_ATTEMPTS):
            try:
                self.brick = find_brick()
                self._motors = self._acquire_motors()
                return
            except Exception as e:
                last_err = e
                time.sleep(_RECONNECT_DELAY_S)
        raise RuntimeError(f"reconnect to NXT brick failed: {last_err}")

    def _run_motor(self, fn):
        """Run a motor call, transparently reconnecting on a dropped USB handle.

        The brick re-enumerates at a new USB address when it sleeps or is
        replugged, stranding our cached handle so motor calls raise USBError
        (ENODEV/EACCES). We dispose the stale handle and re-find the device,
        riding out the re-enumeration window with a few retries, so the daemon
        recovers without a restart. Injected (test) bricks aren't ours to swap.
        """
        if self._owns_connection and self.brick is None:
            self._reconnect()
        try:
            return fn()
        except USBError:
            if not self._owns_connection:
                raise
            print("poked: USB handle dropped; reconnecting to brick", file=sys.stderr)
            self._reconnect()
            return fn()

    def close(self) -> None:
        try:
            self.brick.close()
        except Exception:
            pass

    def _btn(self, button: str) -> ButtonConfig:
        if button not in self.config.buttons:
            raise KeyError(f"unknown button {button!r}")
        return self.config.buttons[button]

    def _buttons(self, spec: str) -> list[str]:
        """Resolve a button spec into a list of configured button names.

        A spec is either a single configured name, or several single-character
        names concatenated (e.g. ``"ab"`` -> ``["a", "b"]``) to actuate them
        together.
        """
        if spec in self.config.buttons:
            return [spec]
        names: list[str] = []
        for ch in spec:
            self._btn(ch)
            if ch not in names:
                names.append(ch)
        if not names:
            raise KeyError(f"no buttons in {spec!r}")
        return names

    def _run_action(self, spec: str, do_one) -> dict:
        self._refresh_config()
        buttons = self._buttons(spec)
        with self._lock:
            try:
                if len(buttons) == 1:
                    # single button keeps auto-reconnect on USB drop, per motor call
                    results = {buttons[0]: do_one(buttons[0], self._run_motor)}
                else:
                    # parallel: reconnect up front, then drive each motor directly so
                    # threads never mutate brick/_motors out from under one another
                    if self._owns_connection and self.brick is None:
                        self._reconnect()
                    results = self._run_parallel(buttons, do_one)
            except Exception:
                # Safety: a blocked/failed turn leaves nxt-python braking against
                # the jam (its finally runs self.brake()). Never let the motor stay
                # stalled — de-energize the involved motors before propagating.
                self._idle_buttons(buttons)
                raise
            return {"buttons": [results[b] for b in buttons]}

    def _idle_motor(self, name: str) -> None:
        try:
            motor = self._motors.get(name)
            if motor is not None:
                motor.idle()
        except Exception:
            pass

    def _idle_buttons(self, buttons: list[str]) -> None:
        for b in buttons:
            cfg = self.config.buttons.get(b)
            if cfg is not None:
                self._idle_motor(cfg.motor)

    def _run_parallel(self, buttons: list[str], do_one) -> dict:
        results: dict[str, dict] = {}
        errors: dict[str, Exception] = {}

        def direct(fn):
            return fn()

        def worker(b: str) -> None:
            try:
                results[b] = do_one(b, direct)
            except Exception as e:
                errors[b] = e

        threads = [threading.Thread(target=worker, args=(b,)) for b in buttons]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            detail = "; ".join(f"{b}: {type(e).__name__}: {e}" for b, e in errors.items())
            raise RuntimeError(f"multi-button action failed ({detail})")
        return results

    def _do_press(self, button: str, run, hold_secs: float) -> dict:
        """Momentary press: drive forward to the configured angle, brake to hold
        the button down for ``hold_secs``, then idle so the spring returns the arm."""
        cfg = self._btn(button)
        run(lambda: self._motors[cfg.motor].turn(cfg.power, cfg.angle, brake=True))
        time.sleep(hold_secs)
        try:
            self._motors[cfg.motor].idle()
        except Exception:
            pass
        return {
            "button": button,
            "motor": cfg.motor,
            "angle": cfg.angle,
            "power": cfg.power,
            "hold_secs": hold_secs,
        }

    def press(self, spec: str, hold_secs: float | None = None) -> dict:
        hold = _DEFAULT_HOLD_S if hold_secs is None else max(0.0, float(hold_secs))
        return self._run_action(spec, lambda b, run: self._do_press(b, run, hold))

    def stop_all(self) -> dict:
        with self._lock:
            for m in self._motors.values():
                try:
                    m.idle()
                except Exception:
                    pass
            return {"stopped": True}

    def status(self) -> dict:
        self._refresh_config()
        return {
            "buttons": {
                name: {
                    "motor": cfg.motor,
                    "angle": cfg.angle,
                    "power": cfg.power,
                }
                for name, cfg in self.config.buttons.items()
            }
        }

    def raw_turn(self, motor: str, power: int, degrees: int) -> dict:
        motor = motor.upper()
        if motor not in ("A", "B", "C"):
            raise KeyError(f"unknown motor {motor!r}")
        with self._lock:
            try:
                self._run_motor(lambda: self._motors[motor].turn(power, degrees))
            except Exception:
                self._idle_motor(motor)  # never leave the motor stalled on a block
                raise
            return {"motor": motor, "power": power, "degrees": degrees}
