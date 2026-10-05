"""Drive a two motor vehicle from navigation hints, one hint per input line.

The hint strings match the ones computed by the ObjectDetection project
(TURN LEFT, TURN RIGHT, GO STRAIGHT, APPROACH, REVERSE, STOP, DEPTH UNKNOWN).
Once the detector prints its hint for every frame, it can be piped in:

    python robot_detection.py --target person | python examples/navigation_hints.py

Left wheel motor on port A, right wheel motor on port B. If no hint arrives
for WATCHDOG_S seconds the vehicle stops, so a crashed detector cannot leave
it driving.
"""

import argparse
import asyncio
import sys

from technic_hub import Color, TechnicHub

WATCHDOG_S = 1.0

# Hint: (left speed, right speed, status light). The right motor is mounted
# mirrored, so it runs with the opposite sign to drive forward.
HINTS: dict[str, tuple[int, int, Color]] = {
    "GO STRAIGHT": (50, -50, Color.GREEN),
    "APPROACH": (30, -30, Color.CYAN),
    "TURN LEFT": (-25, -25, Color.YELLOW),
    "TURN RIGHT": (25, 25, Color.YELLOW),
    "REVERSE": (-30, 30, Color.ORANGE),
    "STOP": (0, 0, Color.RED),
    "DEPTH UNKNOWN": (0, 0, Color.PURPLE),
}


async def apply_hint(hub: TechnicHub, hint: str) -> None:
    """Translate one navigation hint into motor commands.

    Args:
        hub: Connected hub with drive motors on ports A and B.
        hint: One of the keys of `HINTS`; unknown hints are ignored.
    """
    if hint not in HINTS:
        return
    left, right, color = HINTS[hint]
    if left == right == 0:
        await hub.motor("A").stop()
        await hub.motor("B").stop()
    else:
        await hub.motor("A").run(left)
        await hub.motor("B").run(right)
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
                await apply_hint(hub, hint)
                last = hint
        await hub.stop_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-a", "--address", help="Bluetooth address of the hub")
    asyncio.run(main(parser.parse_args().address))
