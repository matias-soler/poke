from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ButtonConfig:
    motor: str
    angle: int
    power: int

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "ButtonConfig":
        motor = str(d["motor"]).upper()
        if motor not in {"A", "B", "C"}:
            raise ValueError(f"button {name!r}: motor must be A, B, or C (got {motor!r})")
        angle = int(d["angle"])
        if angle <= 0:
            raise ValueError(f"button {name!r}: angle must be > 0")
        power = int(d["power"])
        if not -100 <= power <= 100:
            raise ValueError(f"button {name!r}: power must be in [-100, 100]")
        return cls(motor=motor, angle=angle, power=power)


@dataclass(frozen=True)
class Config:
    buttons: dict[str, ButtonConfig]

    @classmethod
    def load(cls, path: Path) -> "Config":
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        section = raw.get("buttons") or {}
        if not section:
            raise ValueError(f"{path}: no [buttons.*] entries defined")
        buttons = {name: ButtonConfig.from_dict(name, b) for name, b in section.items()}
        return cls(buttons=buttons)
