"""Minimal library example: status light, battery and one motor on port A.

Run with:
    python examples/basic_usage.py
"""

import asyncio
import logging

from technic_hub import Color, TechnicHub


async def main() -> None:
    """Connect to the first hub found and exercise the motor on port A."""
    async with TechnicHub() as hub:
        print(f"Battery: {await hub.battery_level()} %")
        print(f"Devices: {hub.describe_devices()}")
        await hub.set_led(Color.GREEN)

        await hub.wait_for_device("A")
        motor = hub.motor("A")
        await motor.reset_position()
        await motor.track_position()

        await motor.run_for_degrees(360, speed=50)
        await motor.run_for_degrees(-180, speed=30)
        print(f"Position: {motor.position} degrees")

        await motor.run_to_position(0, speed=40)
        await hub.set_led(Color.BLUE)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
