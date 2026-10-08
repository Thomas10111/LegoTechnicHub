"""Spin every attached motor briefly and find out which one steers.

Each motor runs slowly forward, then backward, with a low power limit while
its position is sampled. A drive motor keeps turning for the whole run. The
steering motor hits its end stop in both directions and stalls, which shows up
as a position that stops changing. Afterwards the steering motor is moved back
to the middle of its range.

Lift the vehicle (or give it room to roll a little) and press the hub button,
then run:

    python examples/find_steering.py
    python examples/find_steering.py --address 90:84:2B:7D:D3:9A
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass, field

from technic_hub import Color, Motor, TechnicHub
from technic_hub import protocol as p

SPEED = 20  # Regulated speed in percent, slow enough to stall gently.
MAX_POWER = 35  # Power limit in percent, keeps the end stop push soft.
RUN_S = 1.5  # Run time per direction.
SAMPLE_S = 0.05  # Position sampling interval.
STALL_WINDOW_S = 0.4  # A stall means no movement for this long at the end...
STALL_DEG = 5  # ...where "no movement" is less than this many degrees.

# Status light while testing each port.
PORT_COLORS = {0: Color.RED, 1: Color.YELLOW, 2: Color.BLUE, 3: Color.PURPLE}


@dataclass
class Sweep:
    """Positions seen while one motor ran in one direction."""

    direction: int
    samples: list[int] = field(default_factory=list)

    @property
    def travel(self) -> int:
        return abs(self.samples[-1] - self.samples[0]) if self.samples else 0

    @property
    def stalled(self) -> bool:
        window = max(1, round(STALL_WINDOW_S / SAMPLE_S))
        tail = self.samples[-window:]
        return len(self.samples) > window and max(tail) - min(tail) < STALL_DEG


@dataclass
class MotorResult:
    """Outcome of testing one port."""

    port: int
    sweeps: list[Sweep]

    @property
    def low(self) -> int:
        return min(s for sweep in self.sweeps for s in sweep.samples)

    @property
    def high(self) -> int:
        return max(s for sweep in self.sweeps for s in sweep.samples)

    @property
    def stalled_both_ways(self) -> bool:
        return all(sweep.stalled for sweep in self.sweeps)


async def sweep(motor: Motor, direction: int) -> Sweep:
    """Run a motor in one direction for RUN_S seconds and record its position.

    Args:
        motor: Motor with position tracking enabled.
        direction: 1 for forward, -1 for backward.

    Returns:
        The sampled positions.
    """
    result = Sweep(direction)
    await motor.run(direction * SPEED, max_power=MAX_POWER)
    loop = asyncio.get_running_loop()
    end = loop.time() + RUN_S
    while loop.time() < end:
        await asyncio.sleep(SAMPLE_S)
        if motor.position is not None:
            result.samples.append(motor.position)
    await motor.stop()
    await asyncio.sleep(0.3)
    return result


async def test_motor(hub: TechnicHub, port: int) -> MotorResult:
    """Spin one motor both ways and return what it did."""
    name = p.port_name(port)
    print(f"Port {name}: spinning forward and backward...")
    await hub.set_led(PORT_COLORS.get(port, Color.WHITE))
    motor = hub.motor(port)
    await motor.reset_position()
    await motor.track_position()
    await asyncio.sleep(0.2)
    sweeps = [await sweep(motor, 1), await sweep(motor, -1)]
    return MotorResult(port, sweeps)


def pick_steering(results: list[MotorResult]) -> MotorResult | None:
    """Return the motor that behaves like a steering motor, if exactly one does."""
    candidates = [r for r in results if r.stalled_both_ways]
    return candidates[0] if len(candidates) == 1 else None


def print_report(results: list[MotorResult]) -> None:
    print()
    print("Port  Forward          Backward         Range")
    for r in results:
        cells = [
            f"{s.travel:4d} deg {'stall' if s.stalled else 'free '}" for s in r.sweeps
        ]
        print(
            f"  {p.port_name(r.port)}   {cells[0]:<16} {cells[1]:<16} "
            f"{r.high - r.low:4d} deg"
        )
    print()


async def main(address: str | None, name: str | None, timeout: float) -> None:
    async with TechnicHub(address=address, name=name, timeout=timeout) as hub:
        ports = sorted(
            port
            for port, type_id in hub.devices.items()
            if port <= 3 and type_id in p.TACHO_MOTOR_TYPES
        )
        if not ports:
            print("No motors with a rotation sensor attached to ports A to D.")
            return
        print(f"Motors on ports {', '.join(p.port_name(port) for port in ports)}")

        try:
            results = [await test_motor(hub, port) for port in ports]
        finally:
            await hub.stop_all()

        print_report(results)
        steering = pick_steering(results)
        if steering is None:
            stalled = [p.port_name(r.port) for r in results if r.stalled_both_ways]
            print(
                "Could not tell the steering motor apart "
                f"(stalled both ways: {', '.join(stalled) or 'none'}). "
                "Check that the drive wheels can turn freely and retry."
            )
            await hub.set_led(Color.RED)
            return

        center = (steering.low + steering.high) // 2
        print(
            f"Steering motor is on port {p.port_name(steering.port)}: range "
            f"{steering.high - steering.low} deg, centering at {center} deg."
        )
        motor = hub.motor(steering.port)
        await motor.run_to_position(center, speed=SPEED, max_power=MAX_POWER)
        await hub.set_led(Color.GREEN)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-a", "--address", help="Bluetooth address of the hub")
    parser.add_argument("-n", "--name", help="advertised name of the hub")
    parser.add_argument("-t", "--timeout", type=float, default=20.0)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    asyncio.run(main(args.address, args.name, args.timeout))
