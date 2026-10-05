# LEGO Technic Hub over Bluetooth

A Python app and library that controls a LEGO Technic Hub (88012, the Control+
hub) from a host computer over Bluetooth Low Energy. The target host is an NVIDIA
Jetson board.

Nothing runs on the hub itself. The hub keeps its stock LEGO firmware, and this
program sends it LEGO Wireless Protocol 3 (LWP3) commands such as "run motor A at
50 %" or "rotate motor B by 90 degrees". All logic stays on the Jetson, next to
the camera and neural network code.

Other Powered Up hubs that speak LWP3 (City Hub, BOOST Move Hub) work as well.

---

## Requirements

- Python 3.12 (same version as the ObjectDetection project)
- A Bluetooth 4.0+ adapter. The Jetson Orin Nano developer kit has one on
  board; the original Jetson Nano needs a USB dongle or an M.2 Wi-Fi/BT card.
- BlueZ on Linux (preinstalled on JetPack). Windows 10+ and macOS also work for
  development.

---

## Setup on the Jetson

```bash
git clone <this repository> LegoTechnicHub
cd LegoTechnicHub
./scripts/setup_jetson.sh
```

The script installs and starts BlueZ, adds your user to the `bluetooth` group,
installs [uv](https://docs.astral.sh/uv/), and creates `.venv` with Python 3.12.
JetPack's system Python (3.8 or 3.10) is left untouched. Log out and back in
once afterwards, then:

```bash
source .venv/bin/activate
technic-hub scan
```

## Setup on Windows (development)

```cmd
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

---

## Command line app

Switch on the hub (its light blinks while it advertises), then:

```bash
technic-hub scan                      # list hubs in range
technic-hub info                      # name, firmware, battery, attached devices
technic-hub led green                 # set the status light
technic-hub run A 50 --seconds 2      # regulated speed for 2 s, then brake
technic-hub power B -40 --seconds 1   # raw power (also for motors without sensor)
technic-hub rotate A 90 --speed 30    # rotate by 90 degrees
technic-hub goto A 0                  # move to absolute position 0
technic-hub stop                      # stop all motors
technic-hub tilt                      # read the built in tilt sensor
technic-hub off                       # switch the hub off
technic-hub shell                     # interactive prompt over one connection
```

Every command scans for the first hub it finds. With several hubs nearby, pick
one with `-a <address>` (from `scan`) or `-n <name>`. Add `-v` for progress
messages or `-vv` to see every Bluetooth message in hex.

Connecting takes a few seconds, so for several commands in a row use `shell`:

```text
$ technic-hub shell
hub> reset A
hub> rotate A 360 --speed 60
hub> position A
360 degrees
hub> led red
hub> quit
```

You can also pipe a command list into it: `technic-hub shell < moves.txt`.

---

## Library

```python
import asyncio
from technic_hub import Color, TechnicHub


async def main() -> None:
    async with TechnicHub() as hub:
        await hub.set_led(Color.GREEN)
        motor = hub.motor("A")
        await motor.run_for_degrees(360, speed=50)  # waits until finished
        await motor.run(30)                         # keeps running
        await asyncio.sleep(2)
        await motor.stop()
        print(await hub.battery_level(), "%")


asyncio.run(main())
```

Positional commands (`run_for_degrees`, `run_for_time`, `run_to_position`) wait
for the hub to report completion by default. Pass `wait=False` to continue
immediately, for example to move two motors at once. They return `False` when a
newer command on the same port replaced them before they finished.

See `examples/` for more:

- `basic_usage.py`: status light, battery and position control of one motor.
- `navigation_hints.py`: drives a two motor vehicle (left motor on A, right on
  B) from the hint strings computed by the ObjectDetection project (`TURN
  LEFT`, `GO STRAIGHT`, `STOP`, ...), read one per line from stdin. A watchdog
  stops the vehicle when no hint arrives for one second.

---

## Project layout

```
LegoTechnicHub/
├── technic_hub/
│   ├── protocol.py     LWP3 message encoding and decoding (no Bluetooth code)
│   ├── hub.py          TechnicHub and Motor classes on top of bleak
│   └── cli.py          technic-hub command line app and interactive shell
├── examples/           Library usage examples
├── scripts/
│   └── setup_jetson.sh One time Jetson setup (BlueZ, uv, Python 3.12 venv)
└── tests/              Unit tests (no hub or Bluetooth adapter needed)
```

## Development

```bash
pytest          # runs without hardware: protocol bytes and a fake BLE link
black .         # formatter, line length 88
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `no LEGO hub found` | Press the hub button so the light blinks. The hub stops advertising after about 20 s. |
| Hub found but connecting fails on Linux | `bluetoothctl remove <address>`, then retry. A stale pairing entry can block the connection. |
| `org.bluez.Error.NotReady` | `sudo rfkill unblock bluetooth` and `sudo systemctl restart bluetooth`. |
| Permission errors on D-Bus | Make sure you logged out and back in after `setup_jetson.sh` (bluetooth group). |
| `has no rotation sensor` | Train and simple medium motors only support `power`, not `run`, `rotate` or `goto`. |

Protocol reference: <https://lego.github.io/lego-ble-wireless-protocol-docs/>
