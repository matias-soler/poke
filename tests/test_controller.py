from __future__ import annotations

import pytest

from poke.config import ButtonConfig, Config
from poke.controller import Controller

from .conftest import FakeBrick


@pytest.fixture
def cfg() -> Config:
    return Config(buttons={"a": ButtonConfig(motor="A", angle=90, power=75, hold=True)})


@pytest.fixture
def brick() -> FakeBrick:
    return FakeBrick()


@pytest.fixture
def controller(cfg: Config, brick: FakeBrick) -> Controller:
    return Controller(cfg, brick=brick)


def test_press_turns_motor_with_brake(controller: Controller, brick: FakeBrick):
    result = controller.press("a")
    assert result == {"button": "a", "motor": "A", "angle": 90, "power": 75, "hold": True}
    calls = brick.motors[__import__("nxt.motor", fromlist=["Port"]).Port.A].calls
    assert calls == [("turn", (75, 90), {"brake": True})]


def test_unpress_inverts_direction(controller: Controller, brick: FakeBrick):
    controller.press("a")
    result = controller.unpress("a")
    assert result["power"] == -75
    assert result["angle"] == -90
    import nxt.motor

    calls = brick.motors[nxt.motor.Port.A].calls
    assert calls[-1] == ("turn", (-75, 90), {"brake": False})


def test_double_press_raises(controller: Controller):
    controller.press("a")
    with pytest.raises(RuntimeError, match="already pressed"):
        controller.press("a")


def test_unpress_without_press_raises(controller: Controller):
    with pytest.raises(RuntimeError, match="not pressed"):
        controller.unpress("a")


def test_unknown_button_raises(controller: Controller):
    with pytest.raises(KeyError):
        controller.press("zzz")


def test_status_reports_pressed_flag(controller: Controller):
    assert controller.status()["buttons"]["a"]["pressed"] is False
    controller.press("a")
    assert controller.status()["buttons"]["a"]["pressed"] is True


def test_stop_all_clears_state_and_idles_motors(controller: Controller, brick: FakeBrick):
    controller.press("a")
    controller.stop_all()
    assert controller.status()["buttons"]["a"]["pressed"] is False
    import nxt.motor

    assert ("idle", (), {}) in brick.motors[nxt.motor.Port.A].calls


def test_raw_turn_bypasses_state(controller: Controller, brick: FakeBrick):
    import nxt.motor

    result = controller.raw_turn("a", 50, 30)
    assert result == {"motor": "A", "power": 50, "degrees": 30}
    assert ("turn", (50, 30), {"brake": True}) in brick.motors[nxt.motor.Port.A].calls
    assert controller.status()["buttons"]["a"]["pressed"] is False
