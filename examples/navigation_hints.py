"""Drive a steered vehicle from navigation hints, one hint per input line.

The hint strings match the ones computed by the ObjectDetection project
(TURN LEFT, TURN RIGHT, GO STRAIGHT, APPROACH, REVERSE, STOP, DEPTH UNKNOWN).
Once the detector prints its hint for every frame, it can be piped in:

    python robot_detection.py --target person | python examples/navigation_hints.py

Drive motors on ports A and B, steering motor on port D. At startup the
steering is driven gently into both end stops to find its range, then
centered. If no hint arrives for WATCHDOG_S seconds the vehicle stops, so a
crashed detector cannot leave it driving.
"""

import argparse
import asyncio
import sys

from technic_hub import Color, Motor, TechnicHub

WATCHDOG_S = 1.0

# Drive motors and the sign that makes each one drive forward: A drives the
# rear wheels, B the front wheels.
DRIVE = {"A": 1, "B": 1}
STEERING = "D"

# Steering calibration: slow and with a low power limit so the end stops are
# found without straining the gears.
CALIBRATE_SPEED = 20
CALIBRATE_POWER = 35
CALIBRATE_S = 1.2
# Turn to this fraction of the measured half range, short of the end stops.
STEER_FRACTION = 0.8
# Motor direction that steers left (1 forward, -1 backward). On this vehicle,
# running D backward steers left (checked with left_circle.py).
STEER_LEFT_SIGN = -1
STEER_SPEED = 60

# Hint: (drive speed, steering: -1 left, 0 straight, 1 right, status light).
HINTS: dict[str, tuple[int, int, Color]] = {
    "GO STRAIGHT": (50, 0, Color.GREEN),
    "APPROACH": (30, 0, Color.CYAN),
    "TURN LEFT": (30, -1, Color.YELLOW),
    "TURN RIGHT": (30, 1, Color.YELLOW),
    "REVERSE": (-30, 0, Color.ORANGE),
    "STOP": (0, 0, Color.RED),
    "DEPTH UNKNOWN": (0, 0, Color.PURPLE),
}


async def end_stop(motor: Motor, direction: int) -> int:
    """Run the steering into one end stop and return the position there."""
    await motor.run(direction * CALIBRATE_SPEED, max_power=CALIBRATE_POWER)
    await asyncio.sleep(CALIBRATE_S)
    await motor.stop()
    await asyncio.sleep(0.2)
    if motor.position is None:
        raise RuntimeError(f"no position reported by steering motor {STEERING}")
    return motor.position


async def calibrate_steering(hub: TechnicHub) -> tuple[int, int]:
    """Find the steering range and center the steering.

    Args:
        hub: Connected hub with the steering motor on port `STEERING`.

    Returns:
        The center position and the steering angle for a full turn, in degrees.
    """
    motor = hub.motor(STEERING)
    await hub.wait_for_device(STEERING)
    await motor.reset_position()
    await motor.track_position()
    await asyncio.sleep(0.2)
    high = await end_stop(motor, 1)
    low = await end_stop(motor, -1)
    center = (low + high) // 2
    await motor.run_to_position(
        center, speed=CALIBRATE_SPEED, max_power=CALIBRATE_POWER
    )
    steer_deg = round((high - low) / 2 * STEER_FRACTION)
    print(f"Steering range {high - low} deg, turning to +/-{steer_deg} deg")
    return center, steer_deg


async def apply_hint(hub: TechnicHub, hint: str, center: int, steer_deg: int) -> None:
    """Translate one navigation hint into motor commands.

    Args:
        hub: Connected hub with motors on the `DRIVE` and `STEERING` ports.
        hint: One of the keys of `HINTS`; unknown hints are ignored.
        center: Straight ahead steering position, from `calibrate_steering`.
        steer_deg: Steering angle for a full turn, from `calibrate_steering`.
    """
    if hint not in HINTS:
        return
    speed, steer, color = HINTS[hint]
    target = center - steer * STEER_LEFT_SIGN * steer_deg
    await hub.motor(STEERING).run_to_position(target, speed=STEER_SPEED, wait=False)
    for port, sign in DRIVE.items():
        if speed == 0:
            await hub.motor(port).stop()
        else:
            await hub.motor(port).run(sign * speed)
    await hub.set_led(color)


async def read_hints() -> asyncio.StreamReader:
    """Wrap stdin in an asyncio stream (Linux only, which is fine on a Jetson)."""
    reader = asyncio.StreamReader()
    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
    )
    return reader


async def main(address: str | None) -> None:
    """Connect to the hub and follow hints from stdin until end of input."""
    async with TechnicHub(address=address) as hub:
        center, steer_deg = await calibrate_steering(hub)
        reader = await read_hints()
        loop = asyncio.get_running_loop()
        last_hint_at = loop.time()
        last = ""
        while True:
            try:
                async with asyncio.timeout(WATCHDOG_S):
                    line: bytes | None = await reader.readline()
            except TimeoutError:
                line = None
            if line == b"":  # End of input.
                break
            # Accept plain hints as well as log lines that contain one.
            text = line.decode(errors="replace").upper() if line else ""
            hint = next((h for h in HINTS if h in text), None)
            if hint is not None:
                last_hint_at = loop.time()
            elif loop.time() - last_hint_at > WATCHDOG_S:
                hint = "STOP"
            if hint is not None and hint != last:
                await apply_hint(hub, hint, center, steer_deg)
                last = hint
        await hub.stop_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-a", "--address", help="Bluetooth address of the hub")
    asyncio.run(main(parser.parse_args().address))
