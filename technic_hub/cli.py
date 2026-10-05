"""Command line app: send commands to a LEGO Technic Hub over Bluetooth.

Examples:
    technic-hub scan
    technic-hub info
    technic-hub led green
    technic-hub run A 50 --seconds 2
    technic-hub rotate B 90 --speed 30
    technic-hub shell
"""

import argparse
import asyncio
import logging
import shlex
import sys
import threading
from collections.abc import Awaitable, Callable

from . import __version__
from . import protocol as p
from .hub import HubError, TechnicHub

type Handler = Callable[[TechnicHub, argparse.Namespace], Awaitable[None]]

HANDLERS: dict[str, Handler] = {}


def command(name: str) -> Callable[[Handler], Handler]:
    """Register a coroutine as the handler of a hub command."""

    def register(func: Handler) -> Handler:
        HANDLERS[name] = func
        return func

    return register


# Hub commands, usable both from the command line and inside `shell`.


@command("info")
async def cmd_info(hub: TechnicHub, _args: argparse.Namespace) -> None:
    print(f"Name:     {await hub.advertising_name()}")
    print(f"Address:  {hub.address}")
    print(f"Firmware: {await hub.firmware_version()}")
    print(f"Battery:  {await hub.battery_level()} %")
    print("Devices:")
    for port, name in hub.describe_devices().items():
        print(f"  {port:>4}  {name}")


@command("led")
async def cmd_led(hub: TechnicHub, args: argparse.Namespace) -> None:
    await hub.set_led(args.color)


@command("power")
async def cmd_power(hub: TechnicHub, args: argparse.Namespace) -> None:
    motor = hub.motor(args.port)
    await motor.set_power(args.power)
    if args.seconds is not None:
        await asyncio.sleep(args.seconds)
        await motor.stop()


@command("run")
async def cmd_run(hub: TechnicHub, args: argparse.Namespace) -> None:
    motor = hub.motor(args.port)
    if args.seconds is None:
        await motor.run(args.speed)
    else:
        await motor.run_for_time(int(args.seconds * 1000), args.speed)


@command("rotate")
async def cmd_rotate(hub: TechnicHub, args: argparse.Namespace) -> None:
    await hub.motor(args.port).run_for_degrees(args.degrees, args.speed)


@command("goto")
async def cmd_goto(hub: TechnicHub, args: argparse.Namespace) -> None:
    await hub.motor(args.port).run_to_position(args.position, args.speed)


@command("reset")
async def cmd_reset(hub: TechnicHub, args: argparse.Namespace) -> None:
    await hub.motor(args.port).reset_position(args.position)


@command("position")
async def cmd_position(hub: TechnicHub, args: argparse.Namespace) -> None:
    motor = hub.motor(args.port)
    await motor.track_position()
    await asyncio.sleep(0.3)
    print(f"{motor.position} degrees")


@command("stop")
async def cmd_stop(hub: TechnicHub, args: argparse.Namespace) -> None:
    if args.ports:
        for port in args.ports:
            await hub.motor(port).stop(brake=not args.coast)
    else:
        await hub.stop_all(brake=not args.coast)


@command("tilt")
async def cmd_tilt(hub: TechnicHub, _args: argparse.Namespace) -> None:
    await hub.subscribe(p.PORT_TILT, 0)
    await asyncio.sleep(0.3)
    if (raw := hub.port_values.get(p.PORT_TILT)) is None:
        print("no tilt data received")
    else:
        print(f"tilt (x, y, z): {p.decode_int16_list(raw)}")
    await hub.unsubscribe(p.PORT_TILT)


@command("battery")
async def cmd_battery(hub: TechnicHub, _args: argparse.Namespace) -> None:
    print(f"{await hub.battery_level()} %")


@command("off")
async def cmd_off(hub: TechnicHub, _args: argparse.Namespace) -> None:
    await hub.switch_off()


@command("sleep")
async def cmd_sleep(_hub: TechnicHub, args: argparse.Namespace) -> None:
    await asyncio.sleep(args.seconds)


def add_hub_commands(subparsers: argparse._SubParsersAction) -> None:
    """Add every hub command to an argparse subparser group."""

    def add(name: str, help_text: str, port: bool = False) -> argparse.ArgumentParser:
        parser = subparsers.add_parser(name, help=help_text)
        if port:
            parser.add_argument("port", type=p.parse_port, help="port A, B, C or D")
        return parser

    add("info", "show name, firmware, battery and attached devices")

    sp = add("led", "set the status light color")
    sp.add_argument("color", type=str.lower, choices=[c.name.lower() for c in p.Color])

    sp = add("power", "unregulated power, works with any motor", port=True)
    sp.add_argument("power", type=int, help="-100 to 100")
    sp.add_argument("--seconds", type=float, help="stop again after this time")

    sp = add("run", "run a motor at regulated speed", port=True)
    sp.add_argument("speed", type=int, help="-100 to 100")
    sp.add_argument("--seconds", type=float, help="run for this time, then brake")

    sp = add("rotate", "rotate a motor by a number of degrees", port=True)
    sp.add_argument("degrees", type=int)
    sp.add_argument("--speed", type=int, default=50)

    sp = add("goto", "move a motor to an absolute position", port=True)
    sp.add_argument("position", type=int, help="degrees relative to the zero point")
    sp.add_argument("--speed", type=int, default=50)

    sp = add("reset", "define the current motor position", port=True)
    sp.add_argument("position", type=int, nargs="?", default=0)

    add("position", "print the motor position in degrees", port=True)

    sp = add("stop", "stop motors (all motors if no port given)")
    sp.add_argument("ports", type=p.parse_port, nargs="*")
    sp.add_argument(
        "--coast", action="store_true", help="let the motor float instead of braking"
    )

    add("tilt", "print the hub tilt angles")
    add("battery", "print the battery level")
    add("off", "switch the hub off")

    sp = add("sleep", "pause (useful in scripted shell input)")
    sp.add_argument("seconds", type=float)


def build_shell_parser() -> argparse.ArgumentParser:
    """Build the parser used for each line typed into `shell`."""
    parser = argparse.ArgumentParser(prog="", add_help=False, exit_on_error=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_hub_commands(subparsers)
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Build the top level command line parser."""
    parser = argparse.ArgumentParser(
        prog="technic-hub",
        description="Control a LEGO Technic Hub over Bluetooth Low Energy.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "-a", "--address", help="Bluetooth address of the hub (skips matching by name)"
    )
    parser.add_argument(
        "-n", "--name", help="connect only to a hub with this advertised name"
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=10.0,
        help="scan and connect timeout in seconds",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="-v for info, -vv for raw BLE traffic",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    sp = subparsers.add_parser("scan", help="list advertising hubs")
    sp.add_argument("--seconds", type=float, default=5.0)
    subparsers.add_parser("shell", help="interactive prompt over one connection")
    add_hub_commands(subparsers)
    return parser


def start_input_thread(
    loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[str | None]
) -> None:
    """Read stdin in a daemon thread so Ctrl+C never waits on a blocked input().

    Args:
        loop: Event loop that consumes the lines.
        queue: Receives each line, then None at end of input.
    """

    def reader() -> None:
        while True:
            try:
                line: str | None = input()
            except (EOFError, KeyboardInterrupt):
                line = None
            try:
                loop.call_soon_threadsafe(queue.put_nowait, line)
            except RuntimeError:  # The event loop has already closed.
                return
            if line is None:
                return

    threading.Thread(target=reader, daemon=True).start()


async def read_line(queue: asyncio.Queue[str | None], hub: TechnicHub) -> str | None:
    """Prompt for the next line.

    Args:
        queue: Lines from `start_input_thread`.
        hub: Connected hub; a disconnect ends the wait.

    Returns:
        The line, or None at end of input or when the hub disconnects.
    """
    print("hub> ", end="", flush=True)
    line_task = asyncio.ensure_future(queue.get())
    gone_task = asyncio.ensure_future(hub.wait_until_disconnected())
    done, pending = await asyncio.wait(
        {line_task, gone_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    if line_task in done:
        return line_task.result()
    print("\nhub disconnected")
    return None


async def run_shell(hub: TechnicHub) -> None:
    """Run an interactive prompt that sends commands over one connection."""
    parser = build_shell_parser()
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    start_input_thread(asyncio.get_running_loop(), queue)
    print(f"Connected to {hub.address}. Type 'help' for commands, 'quit' to exit.")
    while hub.is_connected:
        if (line := await read_line(queue, hub)) is None:
            break
        match line.strip():
            case "":
                continue
            case "quit" | "exit":
                break
            case "help" | "?":
                parser.print_help()
                continue
            case text if text.startswith("#"):
                continue
            case text:
                pass
        try:
            args = parser.parse_args(shlex.split(text))
        except argparse.ArgumentError as exc:
            print(f"error: {exc}")
            continue
        except SystemExit:
            # argparse printed usage for an unknown or incomplete command.
            continue
        try:
            await HANDLERS[args.command](hub, args)
        except (HubError, TimeoutError, ValueError) as exc:
            print(f"error: {exc or type(exc).__name__}")
        if args.command == "off":
            break


async def run_scan(seconds: float) -> None:
    """Print every hub that advertises within `seconds`."""
    print(f"Scanning for {seconds:.0f} s, press the button on the hub...")
    hubs = await TechnicHub.scan(seconds)
    if not hubs:
        print("No hubs found.")
    for hub in hubs:
        print(f"{hub.address:<20} {hub.name:<22} {hub.kind:<20} RSSI {hub.rssi}")


async def async_main(args: argparse.Namespace) -> int:
    """Execute the parsed command line.

    Args:
        args: Result of `build_parser().parse_args()`.

    Returns:
        Process exit code.
    """
    if args.command == "scan":
        await run_scan(args.seconds)
        return 0

    hub = TechnicHub(address=args.address, name=args.name, timeout=args.timeout)
    await hub.connect()
    try:
        if args.command == "shell":
            await run_shell(hub)
        else:
            await HANDLERS[args.command](hub, args)
    finally:
        await hub.disconnect()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point of the `technic-hub` command."""
    args = build_parser().parse_args(argv)
    level = {0: logging.WARNING, 1: logging.INFO}.get(args.verbose, logging.DEBUG)
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        return 130
    except (HubError, TimeoutError) as exc:
        print(f"error: {exc or type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
