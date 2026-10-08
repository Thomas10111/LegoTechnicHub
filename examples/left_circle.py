"""Drive a left circle: full left steering, forward for a set time, then stop.

Motor ports, drive directions and the steering calibration come from
navigation_hints.py. How long a full circle takes depends on the floor and the
speed. At 30 % on the test floor one circle took about 12 s:

    python examples/left_circle.py -a 90:84:2B:7D:D3:9A
    python examples/left_circle.py -a 90:84:2B:7D:D3:9A --seconds 9 --speed 40
"""

import argparse
import asyncio

from navigation_hints import DRIVE, STEER_LEFT_SIGN, STEER_SPEED, STEERING
from navigation_hints import calibrate_steering
from technic_hub import Color, TechnicHub


async def main(address: str | None, seconds: float, speed: int) -> None:
    """Connect, steer fully left, drive forward for `seconds`, then stop."""
    async with TechnicHub(address=address) as hub:
        center, steer_deg = await calibrate_steering(hub)
        steering = hub.motor(STEERING)
        await steering.run_to_position(
            center + STEER_LEFT_SIGN * steer_deg, speed=STEER_SPEED
        )
        await hub.set_led(Color.YELLOW)
        try:
            for port, sign in DRIVE.items():
                await hub.motor(port).run(sign * speed)
            await asyncio.sleep(seconds)
        finally:
            for port in DRIVE:
                await hub.motor(port).stop()
        await steering.run_to_position(center, speed=STEER_SPEED)
        await hub.set_led(Color.GREEN)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-a", "--address", help="Bluetooth address of the hub")
    parser.add_argument(
        "-s", "--seconds", type=float, default=12.0, help="driving time (default 12)"
    )
    parser.add_argument(
        "--speed", type=int, default=30, help="drive speed in percent (default 30)"
    )
    args = parser.parse_args()
    asyncio.run(main(args.address, args.seconds, args.speed))
