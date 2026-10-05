# CLAUDE.md: LegoTechnicHub

Python app and library that controls a LEGO Technic Hub over Bluetooth LE (LWP3
protocol via `bleak`). Commands are sent from the host; no code runs on the hub.
Deployment target is an NVIDIA Jetson, next to the ObjectDetection project.

## Python

Python 3.12, same as ObjectDetection. Code may use 3.12 features (`type` aliases,
`match`, `asyncio.timeout`) but nothing newer.

```cmd
.venv\Scripts\activate
pip install -e ".[dev]"
```

On the Jetson, `scripts/setup_jetson.sh` creates `.venv` with Python 3.12 via uv.

## Layout

- `technic_hub/protocol.py`: pure LWP3 encoding and decoding, no Bluetooth imports.
  Add new message types here first, with byte level tests.
- `technic_hub/hub.py`: `TechnicHub` connection, `Motor` wrapper, feedback tracking.
- `technic_hub/cli.py`: `technic-hub` command. A hub command is a `@command`
  handler plus its parser in `add_hub_commands`; both the CLI and `shell` use it.

## Code style

- Formatter: `black` (line length 88). Run `black .` before committing.
- Type hints on all function signatures, Google style docstrings on public API.

## Tests

`pytest` runs without hardware. `tests/test_hub.py` uses a `FakeHub` that records
writes and injects notifications.
