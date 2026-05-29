from __future__ import annotations

from pathlib import Path

import pytest

from poke.config import ButtonConfig, Config


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body)
    return p


def test_load_single_button(tmp_path: Path):
    cfg = Config.load(
        _write(
            tmp_path,
            """
            [buttons.a]
            motor = "A"
            angle = 90
            power = 75
            """,
        )
    )
    assert cfg.buttons == {"a": ButtonConfig(motor="A", angle=90, power=75)}


def test_motor_normalised_to_upper(tmp_path: Path):
    cfg = Config.load(
        _write(
            tmp_path,
            """
            [buttons.a]
            motor = "a"
            angle = 30
            power = 50
            """,
        )
    )
    assert cfg.buttons["a"].motor == "A"


def test_rejects_unknown_motor(tmp_path: Path):
    with pytest.raises(ValueError, match="motor must be"):
        Config.load(
            _write(
                tmp_path,
                """
                [buttons.a]
                motor = "D"
                angle = 30
                power = 50
                """,
            )
        )


def test_rejects_non_positive_angle(tmp_path: Path):
    with pytest.raises(ValueError, match="angle must be"):
        Config.load(
            _write(
                tmp_path,
                """
                [buttons.a]
                motor = "A"
                angle = 0
                power = 50
                """,
            )
        )


@pytest.mark.parametrize("power", [-101, 101, 200])
def test_rejects_out_of_range_power(tmp_path: Path, power: int):
    with pytest.raises(ValueError, match="power must be"):
        Config.load(
            _write(
                tmp_path,
                f"""
                [buttons.a]
                motor = "A"
                angle = 30
                power = {power}
                """,
            )
        )


def test_rejects_empty_config(tmp_path: Path):
    with pytest.raises(ValueError, match="no \\[buttons"):
        Config.load(_write(tmp_path, ""))
