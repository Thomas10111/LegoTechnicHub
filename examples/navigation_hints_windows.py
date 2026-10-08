"""Windows version of navigation_hints.py: drive from hints on stdin.

The asyncio event loop on Windows cannot read stdin as a pipe, so a thread
reads the lines instead. Motor setup, steering calibration and the hint table
come from navigation_hints.py. Type hints by hand to test the vehicle:

    python examples/navigation_hints_windows.py -a 90:84:2B:7D:D3:9A
    TURN LEFT

Each hint holds for WATCHDOG_S seconds; without a new one the vehicle stops.
End input with Ctrl+Z and Enter.
"""

import argparse
import asyncio
import sys
import threading

from navigation_hints import HINTS, WATCHDOG_S, apply_hint, calibrate_steering
from technic_hub import TechnicHub


def read_hints() -> asyncio.Queue[str]:
    """Read stdin lines in a thread; an empty string marks end of input."""
    queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def reader() -> None:
        for line in sys.stdin:
            loop.call_soon_threadsafe(queue.put_nowait, line)
        loop.call_soon_threadsafe(queue.put_nowait, "")

    threading.Thread(target=reader, daemon=True).start()
    return queue


async def main(address: str | None) -> None:
    """Connect to the hub and follow hints from stdin until end of input."""
    async with TechnicHub(address=address) as hub:
        center, steer_deg = await calibrate_steering(hub)
        queue = read_hints()
        loop = asyncio.get_running_loop()
        last_hint_at = loop.time()
        last = ""
        while True:
            try:
                async with asyncio.timeout(WATCHDOG_S):
                    line: str | None = await queue.get()
            except TimeoutError:
                line = None
            if line == "":  # End of input.
                break
            # Accept plain hints as well as log lines that contain one.
            text = line.upper() if line else ""
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
