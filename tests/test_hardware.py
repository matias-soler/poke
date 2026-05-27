"""Opt-in hardware smoke test. Requires a real NXT brick on USB.

Run with:  POKE_HARDWARE=1 pytest tests/test_hardware.py -s
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("POKE_HARDWARE") != "1",
    reason="hardware test; set POKE_HARDWARE=1 to enable",
)


def test_find_brick_and_nudge_motor_a():
    from poke.config import ButtonConfig, Config
    from poke.controller import Controller, find_brick

    brick = find_brick()
    assert brick is not None

    cfg = Config(buttons={"a": ButtonConfig(motor="A", angle=15, power=40, hold=False)})
    controller = Controller(cfg, brick=brick)
    try:
        controller.press("a")
        controller.unpress("a")
    finally:
        controller.close()
