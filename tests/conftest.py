from __future__ import annotations

import nxt.motor


class FakeMotor:
    def __init__(self, port: nxt.motor.Port):
        self.port = port
        self.calls: list[tuple[str, tuple, dict]] = []

    def turn(self, power, tacho_units, brake=True, **kwargs):
        self.calls.append(("turn", (power, tacho_units), {"brake": brake, **kwargs}))

    def idle(self):
        self.calls.append(("idle", (), {}))


class FakeBrick:
    def __init__(self):
        self.motors = {p: FakeMotor(p) for p in (nxt.motor.Port.A, nxt.motor.Port.B, nxt.motor.Port.C)}
        self.closed = False

    def get_motor(self, port: nxt.motor.Port) -> FakeMotor:
        return self.motors[port]

    def close(self):
        self.closed = True
