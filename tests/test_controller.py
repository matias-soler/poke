from __future__ import annotations

import nxt.motor
import pytest
from usb.core import USBError

from poke.config import ButtonConfig, Config
from poke.controller import Controller

from .conftest import FakeBrick


@pytest.fixture
def cfg() -> Config:
    return Config(buttons={"a": ButtonConfig(motor="A", angle=90, power=75)})


@pytest.fixture
def brick() -> FakeBrick:
    return FakeBrick()


@pytest.fixture
def controller(cfg: Config, brick: FakeBrick) -> Controller:
    return Controller(cfg, brick=brick)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # press holds (sleeps) before releasing; skip the real wait in unit tests
    monkeypatch.setattr("poke.controller.time.sleep", lambda *_a: None)


def test_press_drives_forward_then_releases(controller: Controller, brick: FakeBrick):
    result = controller.press("a")
    assert result == {
        "buttons": [{"button": "a", "motor": "A", "angle": 90, "power": 75, "hold_secs": 0.2}]
    }
    assert brick.motors[nxt.motor.Port.A].calls == [
        ("turn", (75, 90), {"brake": True}),
        ("idle", (), {}),
    ]


def test_press_holds_for_requested_seconds(controller: Controller, brick: FakeBrick, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("poke.controller.time.sleep", lambda s: slept.append(s))
    result = controller.press("a", hold_secs=5)
    assert result["buttons"][0]["hold_secs"] == 5.0
    assert 5.0 in slept
    assert brick.motors[nxt.motor.Port.A].calls == [
        ("turn", (75, 90), {"brake": True}),
        ("idle", (), {}),
    ]


def test_unknown_button_raises(controller: Controller):
    with pytest.raises(KeyError):
        controller.press("zzz")


def test_status_reports_config_without_pressed_flag(controller: Controller):
    a = controller.status()["buttons"]["a"]
    assert a == {"motor": "A", "angle": 90, "power": 75}
    assert "pressed" not in a


def test_stop_all_idles_motors(controller: Controller, brick: FakeBrick):
    controller.press("a")
    controller.stop_all()
    assert ("idle", (), {}) in brick.motors[nxt.motor.Port.A].calls


def test_raw_turn_issues_turn(controller: Controller, brick: FakeBrick):
    result = controller.raw_turn("a", 50, 30)
    assert result == {"motor": "A", "power": 50, "degrees": 30}
    assert ("turn", (50, 30), {"brake": True}) in brick.motors[nxt.motor.Port.A].calls


def test_press_reconnects_on_dropped_usb_handle(cfg: Config, monkeypatch):
    stale, fresh = FakeBrick(), FakeBrick()
    bricks = [stale, fresh]
    monkeypatch.setattr("poke.controller.find_brick", lambda: bricks.pop(0))

    def enodev(*_a, **_k):
        raise USBError("No such device", errno=19)

    stale.motors[nxt.motor.Port.A].turn = enodev

    controller = Controller(cfg)  # brick=None -> owns connection, find_brick() -> stale

    result = controller.press("a")

    assert result["buttons"][0]["button"] == "a"
    assert fresh.motors[nxt.motor.Port.A].calls == [("turn", (75, 90), {"brake": True}), ("idle", (), {})]
    assert stale.closed is True


def test_press_retries_reconnect_until_success(cfg: Config, monkeypatch):
    stale, fresh = FakeBrick(), FakeBrick()
    finds = [stale, USBError("Access denied", errno=13), fresh]

    def fake_find():
        item = finds.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("poke.controller.find_brick", fake_find)
    monkeypatch.setattr("poke.controller.time.sleep", lambda *_a: None)

    def enodev(*_a, **_k):
        raise USBError("No such device", errno=19)

    stale.motors[nxt.motor.Port.A].turn = enodev

    controller = Controller(cfg)  # find_brick() -> stale
    result = controller.press("a")  # turn -> USBError; reconnect: find fails once, then fresh

    assert result["buttons"][0]["button"] == "a"
    assert fresh.motors[nxt.motor.Port.A].calls == [("turn", (75, 90), {"brake": True}), ("idle", (), {})]


def test_failed_reconnect_raises_cleanly_then_recovers(cfg: Config, monkeypatch):
    stale, fresh = FakeBrick(), FakeBrick()
    finds = [stale] + [USBError("Access denied", errno=13)] * 5 + [fresh]

    def fake_find():
        item = finds.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("poke.controller.find_brick", fake_find)
    monkeypatch.setattr("poke.controller.time.sleep", lambda *_a: None)

    def enodev(*_a, **_k):
        raise USBError("No such device", errno=19)

    stale.motors[nxt.motor.Port.A].turn = enodev

    controller = Controller(cfg)
    with pytest.raises(RuntimeError, match="reconnect to NXT brick failed"):
        controller.press("a")

    assert controller.brick is None

    result = controller.press("a")  # top-of-call guard reconnects to fresh
    assert result["buttons"][0]["button"] == "a"
    assert fresh.motors[nxt.motor.Port.A].calls == [("turn", (75, 90), {"brake": True}), ("idle", (), {})]


def test_blocked_press_idles_motor_for_safety(controller: Controller, brick: FakeBrick):
    motor = brick.motors[nxt.motor.Port.A]

    def blocked(*_a, **_k):
        raise nxt.motor.BlockedException("Blocked!")

    motor.turn = blocked
    with pytest.raises(nxt.motor.BlockedException):
        controller.press("a")
    assert motor.calls == [("idle", (), {})]


def test_blocked_raw_turn_idles_motor_for_safety(controller: Controller, brick: FakeBrick):
    motor = brick.motors[nxt.motor.Port.A]

    def blocked(*_a, **_k):
        raise nxt.motor.BlockedException("Blocked!")

    motor.turn = blocked
    with pytest.raises(nxt.motor.BlockedException):
        controller.raw_turn("a", 50, 30)
    assert motor.calls == [("idle", (), {})]


def test_blocked_multi_button_idles_all_involved_motors(brick: FakeBrick):
    cfg = Config(
        buttons={
            "a": ButtonConfig(motor="A", angle=90, power=75),
            "b": ButtonConfig(motor="B", angle=45, power=60),
        }
    )

    def blocked(*_a, **_k):
        raise nxt.motor.BlockedException("Blocked!")

    brick.motors[nxt.motor.Port.B].turn = blocked
    controller = Controller(cfg, brick=brick)

    with pytest.raises(RuntimeError, match="multi-button action failed"):
        controller.press("ab")
    assert ("idle", (), {}) in brick.motors[nxt.motor.Port.A].calls
    assert ("idle", (), {}) in brick.motors[nxt.motor.Port.B].calls


def test_multi_button_press_actuates_both(brick: FakeBrick):
    cfg = Config(
        buttons={
            "a": ButtonConfig(motor="A", angle=90, power=75),
            "b": ButtonConfig(motor="B", angle=45, power=60),
        }
    )
    controller = Controller(cfg, brick=brick)

    result = controller.press("ab")

    assert result == {
        "buttons": [
            {"button": "a", "motor": "A", "angle": 90, "power": 75, "hold_secs": 0.2},
            {"button": "b", "motor": "B", "angle": 45, "power": 60, "hold_secs": 0.2},
        ]
    }
    assert brick.motors[nxt.motor.Port.A].calls == [("turn", (75, 90), {"brake": True}), ("idle", (), {})]
    assert brick.motors[nxt.motor.Port.B].calls == [("turn", (60, 45), {"brake": True}), ("idle", (), {})]


def test_multi_button_unknown_member_raises(brick: FakeBrick):
    cfg = Config(buttons={"a": ButtonConfig(motor="A", angle=90, power=75)})
    controller = Controller(cfg, brick=brick)
    with pytest.raises(KeyError):
        controller.press("ax")


def test_multi_button_failure_is_reported(brick: FakeBrick):
    cfg = Config(
        buttons={
            "a": ButtonConfig(motor="A", angle=90, power=75),
            "b": ButtonConfig(motor="B", angle=45, power=60),
        }
    )

    def boom(*_a, **_k):
        raise RuntimeError("motor jammed")

    brick.motors[nxt.motor.Port.B].turn = boom
    controller = Controller(cfg, brick=brick)

    with pytest.raises(RuntimeError, match="multi-button action failed"):
        controller.press("ab")


def test_config_path_auto_reloads_before_action(brick: FakeBrick, tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[buttons.a]\nmotor = \"A\"\nangle = 20\npower = 55\n")
    initial = Config.load(cfg_file)
    controller = Controller(initial, brick=brick, config_path=cfg_file)

    cfg_file.write_text("[buttons.a]\nmotor = \"A\"\nangle = 90\npower = 75\n")
    result = controller.press("a")

    assert result["buttons"][0]["angle"] == 90
    assert result["buttons"][0]["power"] == 75
    assert brick.motors[nxt.motor.Port.A].calls == [("turn", (75, 90), {"brake": True}), ("idle", (), {})]


def test_no_config_path_keeps_static_config(controller: Controller, brick: FakeBrick):
    # the shared `controller` fixture has no config_path -> never touches disk
    result = controller.press("a")
    assert result["buttons"][0]["angle"] == 90


def test_startup_without_brick_does_not_crash(cfg: Config, monkeypatch):
    monkeypatch.setattr("poke.controller.time.sleep", lambda *_a: None)

    def no_brick():
        raise RuntimeError("no NXT brick found on USB")

    monkeypatch.setattr("poke.controller.find_brick", no_brick)

    controller = Controller(cfg)  # must not raise even though the brick is absent
    assert controller.brick is None

    # status works without a brick (config only)
    assert "a" in controller.status()["buttons"]

    # an action surfaces a clean error instead of crashing
    with pytest.raises(RuntimeError):
        controller.press("a")


def test_startup_connects_when_brick_returns(cfg: Config, brick: FakeBrick, monkeypatch):
    monkeypatch.setattr("poke.controller.time.sleep", lambda *_a: None)
    calls = {"n": 0}

    def maybe_brick():
        calls["n"] += 1
        if calls["n"] <= 6:  # absent during startup's retries
            raise RuntimeError("no NXT brick found on USB")
        return brick

    monkeypatch.setattr("poke.controller.find_brick", maybe_brick)

    controller = Controller(cfg)  # starts without a brick
    assert controller.brick is None

    result = controller.press("a")  # on-demand reconnect now finds the brick
    assert result["buttons"][0]["button"] == "a"
    assert ("turn", (75, 90), {"brake": True}) in brick.motors[nxt.motor.Port.A].calls


def test_injected_brick_does_not_reconnect(cfg: Config, brick: FakeBrick, monkeypatch):
    def boom():
        raise AssertionError("find_brick must not be called for an injected brick")

    monkeypatch.setattr("poke.controller.find_brick", boom)

    def enodev(*_a, **_k):
        raise USBError("No such device", errno=19)

    brick.motors[nxt.motor.Port.A].turn = enodev
    controller = Controller(cfg, brick=brick)

    with pytest.raises(USBError):
        controller.press("a")
