from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field

import nxt.brick
import nxt.locator
import nxt.motor
from nxt.backend.usb import USBSock

from poke.config import ButtonConfig, Config


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
        raise RuntimeError("no NXT brick found on USB (vendor 0x0694, product 0x0002)")
    sock = USBSock(dev)
    dev.set_configuration()
    intf = dev.get_active_configuration()[(0, 0)]
    sock._epout, sock._epin = intf
    return nxt.brick.Brick(sock)


@dataclass
class ButtonState:
    pressed: bool = False


class Controller:
    """Owns the NXT brick connection and the per-button press state."""

    def __init__(self, config: Config, brick: object | None = None):
        self.config = config
        self.brick = brick if brick is not None else find_brick()
        self._motors = {
            "A": self.brick.get_motor(nxt.motor.Port.A),
            "B": self.brick.get_motor(nxt.motor.Port.B),
            "C": self.brick.get_motor(nxt.motor.Port.C),
        }
        self._state: dict[str, ButtonState] = {name: ButtonState() for name in config.buttons}
        self._lock = threading.Lock()

    def close(self) -> None:
        try:
            self.brick.close()
        except Exception:
            pass

    def _btn(self, button: str) -> ButtonConfig:
        if button not in self.config.buttons:
            raise KeyError(f"unknown button {button!r}")
        return self.config.buttons[button]

    def press(self, button: str) -> dict:
        cfg = self._btn(button)
        with self._lock:
            state = self._state[button]
            if state.pressed:
                raise RuntimeError(f"button {button!r} is already pressed")
            self._motors[cfg.motor].turn(cfg.power, cfg.angle, brake=cfg.hold)
            state.pressed = True
            return {
                "button": button,
                "motor": cfg.motor,
                "angle": cfg.angle,
                "power": cfg.power,
                "hold": cfg.hold,
            }

    def unpress(self, button: str) -> dict:
        cfg = self._btn(button)
        with self._lock:
            state = self._state[button]
            if not state.pressed:
                raise RuntimeError(f"button {button!r} is not pressed")
            self._motors[cfg.motor].turn(-cfg.power, cfg.angle, brake=False)
            state.pressed = False
            return {"button": button, "motor": cfg.motor, "angle": -cfg.angle, "power": -cfg.power}

    def stop_all(self) -> dict:
        with self._lock:
            for m in self._motors.values():
                try:
                    m.idle()
                except Exception:
                    pass
            for s in self._state.values():
                s.pressed = False
            return {"stopped": True}

    def status(self) -> dict:
        return {
            "buttons": {
                name: {
                    "pressed": self._state[name].pressed,
                    "motor": cfg.motor,
                    "angle": cfg.angle,
                    "power": cfg.power,
                    "hold": cfg.hold,
                }
                for name, cfg in self.config.buttons.items()
            }
        }

    def raw_turn(self, motor: str, power: int, degrees: int) -> dict:
        motor = motor.upper()
        if motor not in self._motors:
            raise KeyError(f"unknown motor {motor!r}")
        with self._lock:
            self._motors[motor].turn(power, degrees)
            return {"motor": motor, "power": power, "degrees": degrees}
