# Quick Start

Connect to a LEGO Technic Hub and make a motor turn in five steps.

## 1. Install (once)

On the Jetson:

```bash
cd LegoTechnicHub
./scripts/setup_jetson.sh
```

Log out and back in once so the `bluetooth` group applies.

On Windows (for development):

```cmd
cd LegoTechnicHub
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## 2. Activate the environment

```bash
source .venv/bin/activate        # Jetson
```

```cmd
.venv\Scripts\activate           :: Windows
```

## 3. Switch on the hub and find it

Press the green button on the hub. The light blinks while the hub is waiting
for a connection (about 20 seconds). Then run:

```bash
technic-hub scan
```

```text
Scanning for 5 s, press the button on the hub...
90:84:2B:12:34:56    Technic Hub            Technic Hub          RSSI -58
```

Note the address in the first column. If the list is empty, press the button
again and repeat.

## 4. Connect and check the hub

```bash
technic-hub info
```

```text
Name:     Technic Hub
Address:  90:84:2B:12:34:56
Firmware: 1.1.00.0000
Battery:  87 %
Devices:
     A  Technic Large Motor
  0x32  RGB Light
  ...
```

Every command connects on its own, runs, and disconnects. It picks the first
hub it finds. With several hubs nearby, add the address from step 3:

```bash
technic-hub -a 90:84:2B:12:34:56 info
```

## 5. Run a command

With a motor plugged into port A:

```bash
technic-hub rotate A 90          # turn motor A by 90 degrees
technic-hub run A 50 --seconds 2 # run at 50 % speed for 2 seconds
technic-hub led green            # set the hub light to green
technic-hub stop                 # stop all motors
```

## Several commands over one connection

Connecting takes a few seconds, so use the shell for a sequence of commands:

```text
$ technic-hub shell
Connected to 90:84:2B:12:34:56. Type 'help' for commands, 'quit' to exit.
hub> led blue
hub> rotate A 360 --speed 60
hub> rotate A -360
hub> quit
```

## From Python

```python
import asyncio

from technic_hub import Color, TechnicHub


async def main() -> None:
    async with TechnicHub() as hub:  # TechnicHub(address="90:84:...") for a specific hub
        await hub.set_led(Color.GREEN)
        await hub.motor("A").run_for_degrees(90, speed=50)


asyncio.run(main())
```

## If something goes wrong

| Symptom | Fix |
|---|---|
| `no LEGO hub found` | Press the hub button so the light blinks, then retry within 20 s. |
| Found in `scan` but `info` fails (Linux) | Run `bluetoothctl remove <address>` and retry. |
| `org.bluez.Error.NotReady` | Run `sudo rfkill unblock bluetooth` and `sudo systemctl restart bluetooth`. |
| `has no rotation sensor` | That motor only supports `power`, for example `technic-hub power A 50 --seconds 1`. |

Add `-vv` to any command to see every Bluetooth message. See `README.md` for
all commands and the library API.
