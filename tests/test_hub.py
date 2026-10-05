"""Exercise TechnicHub message handling with a fake BLE link."""

import asyncio

import pytest

from technic_hub import protocol as p
from technic_hub.hub import HubError, TechnicHub, format_version

LARGE_MOTOR_ON_A = "0f 00 04 00 01 2e 00 00 10 00 00 00 10 00 00"


class FakeHub(TechnicHub):
    """TechnicHub that records writes instead of using Bluetooth."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[bytes] = []

    @property
    def is_connected(self) -> bool:
        return True

    async def write(self, message: bytes) -> None:
        self.sent.append(bytes(message))

    def receive(self, hex_text: str) -> None:
        self._on_notify(None, bytearray.fromhex(hex_text))


def test_attach_and_detach() -> None:
    hub = FakeHub()
    hub.receive(LARGE_MOTOR_ON_A)
    hub.receive("0f 00 04 32 01 17 00 00 00 00 10 00 00 00 10")
    assert hub.describe_devices() == {"A": "Technic Large Motor", "0x32": "RGB Light"}
    hub.receive("05 00 04 00 00")
    assert 0 not in hub.devices


async def test_wait_for_command_completion() -> None:
    hub = FakeHub()
    task = asyncio.create_task(hub.motor("A").run_for_degrees(90, 50, wait=True))
    await asyncio.sleep(0)
    assert hub.sent == [p.start_speed_for_degrees(0, 90, 50)]
    hub.receive("05 00 82 00 01")  # in progress
    await asyncio.sleep(0)
    assert not task.done()
    hub.receive("05 00 82 00 0a")  # completed and idle
    assert await task is True


async def test_replaced_command_reports_discarded() -> None:
    hub = FakeHub()
    first = asyncio.create_task(hub.motor("B").run_for_degrees(720, 50))
    await asyncio.sleep(0)
    second = asyncio.create_task(hub.motor("B").run_to_position(0))
    await asyncio.sleep(0)
    hub.receive("05 00 82 01 05")  # first discarded, second in progress
    hub.receive("05 00 82 01 0a")  # second completed
    assert (await first, await second) == (False, True)


async def test_disconnect_fails_pending_commands() -> None:
    hub = FakeHub()
    task = asyncio.create_task(hub.motor("A").run_for_time(1000, 50))
    await asyncio.sleep(0)
    hub._on_disconnect(None)
    with pytest.raises(HubError):
        await task


async def test_battery_level() -> None:
    hub = FakeHub()
    task = asyncio.create_task(hub.battery_level())
    await asyncio.sleep(0)
    assert hub.sent == [bytes.fromhex("05 00 01 06 05")]
    hub.receive("06 00 01 06 06 4b")
    assert await task == 75


async def test_wait_for_device() -> None:
    hub = FakeHub()
    task = asyncio.create_task(hub.wait_for_device("A", timeout=1))
    await asyncio.sleep(0)
    hub.receive(LARGE_MOTOR_ON_A)
    assert await task == 0x2E


async def test_motor_position_updates_and_callback() -> None:
    hub = FakeHub()
    seen: list[bytes] = []
    hub.receive(LARGE_MOTOR_ON_A)
    await hub.subscribe(
        "A", p.MOTOR_MODE_POSITION, callback=lambda port, raw: seen.append(raw)
    )
    hub.receive("08 00 45 00 68 01 00 00")  # 360 degrees
    assert hub.motor("A").position == 360
    assert seen == [bytes.fromhex("68 01 00 00")]


async def test_basic_motor_rejects_speed_commands() -> None:
    hub = FakeHub()
    hub.receive("0f 00 04 00 01 02 00 00 10 00 00 00 10 00 00")  # train motor
    with pytest.raises(HubError):
        await hub.motor("A").run(50)
    await hub.motor("A").set_power(50)


def test_generic_error_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    FakeHub().receive("05 00 05 81 06")
    assert "Invalid use" in caplog.text


def test_format_version() -> None:
    assert format_version(0x17000013) == "1.7.00.0013"
