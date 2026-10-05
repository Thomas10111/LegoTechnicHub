"""Async client that controls a LEGO Technic Hub over Bluetooth Low Energy.

All logic runs on the host (for example a Jetson board). The hub keeps its stock
LEGO firmware and simply executes the LWP3 commands it receives.
"""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Self

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from . import protocol as p

log = logging.getLogger(__name__)

type PortLike = str | int
type ValueCallback = Callable[[int, bytes], Awaitable[None] | None]


class HubError(Exception):
    """Raised for connection problems and errors reported by the hub."""


@dataclass
class DiscoveredHub:
    address: str
    name: str
    kind: str
    rssi: int | None


class Motor:
    """Convenience wrapper for a motor attached to one hub port.

    Args:
        hub: Connected hub the motor is attached to.
        port: LWP3 port id.
    """

    def __init__(self, hub: "TechnicHub", port: int) -> None:
        self.hub = hub
        self.port = port

    @property
    def type_id(self) -> int | None:
        return self.hub.devices.get(self.port)

    @property
    def position(self) -> int | None:
        """Last reported position in degrees (needs `track_position()`)."""
        if self.hub.port_modes.get(self.port) != p.MOTOR_MODE_POSITION:
            return None
        raw = self.hub.port_values.get(self.port)
        return p.decode_int(raw) if raw else None

    def _require_tacho(self) -> None:
        type_id = self.type_id
        if type_id is not None and type_id not in p.TACHO_MOTOR_TYPES:
            raise HubError(
                f"port {p.port_name(self.port)}: {p.device_name(type_id)} "
                "has no rotation sensor, use set_power()"
            )

    async def set_power(self, power: int) -> None:
        """Apply unregulated power from -100 to 100. Works on every motor type."""
        await self.hub.send_output(self.port, p.start_power(self.port, power))

    async def run(self, speed: int, max_power: int = 100) -> None:
        """Run continuously at a regulated speed from -100 to 100."""
        self._require_tacho()
        msg = p.start_speed(self.port, speed, max_power)
        await self.hub.send_output(self.port, msg)

    async def run_for_time(
        self,
        time_ms: int,
        speed: int,
        max_power: int = 100,
        end_state: int = p.EndState.BRAKE,
        wait: bool = True,
    ) -> bool:
        """Run for a fixed time.

        Args:
            time_ms: Duration in milliseconds (at most 65535).
            speed: Regulated speed from -100 to 100.
            max_power: Power limit in percent.
            end_state: Motor behavior after the run.
            wait: Return only after the hub reports the command finished.

        Returns:
            False if a newer command on the same port replaced this one.
        """
        self._require_tacho()
        msg = p.start_speed_for_time(self.port, time_ms, speed, max_power, end_state)
        return await self.hub.send_output(self.port, msg, wait=wait)

    async def run_for_degrees(
        self,
        degrees: int,
        speed: int,
        max_power: int = 100,
        end_state: int = p.EndState.BRAKE,
        wait: bool = True,
    ) -> bool:
        """Rotate by a relative angle.

        Args:
            degrees: Angle to rotate; negative values reverse the direction.
            speed: Regulated speed from -100 to 100.
            max_power: Power limit in percent.
            end_state: Motor behavior after the rotation.
            wait: Return only after the hub reports the command finished.

        Returns:
            False if a newer command on the same port replaced this one.
        """
        self._require_tacho()
        msg = p.start_speed_for_degrees(self.port, degrees, speed, max_power, end_state)
        return await self.hub.send_output(self.port, msg, wait=wait)

    async def run_to_position(
        self,
        position: int,
        speed: int = 50,
        max_power: int = 100,
        end_state: int = p.EndState.HOLD,
        wait: bool = True,
    ) -> bool:
        """Move to an absolute angle relative to the zero point.

        Args:
            position: Target angle in degrees.
            speed: Regulated speed from 0 to 100.
            max_power: Power limit in percent.
            end_state: Motor behavior after reaching the target.
            wait: Return only after the hub reports the command finished.

        Returns:
            False if a newer command on the same port replaced this one.
        """
        self._require_tacho()
        msg = p.goto_absolute_position(self.port, position, speed, max_power, end_state)
        return await self.hub.send_output(self.port, msg, wait=wait)

    async def stop(self, brake: bool = True) -> None:
        """Stop the motor, either braking actively or letting it coast."""
        power = p.POWER_BRAKE if brake else p.POWER_FLOAT
        await self.hub.send_output(self.port, p.start_power(self.port, power))

    async def reset_position(self, position: int = 0) -> None:
        """Define the current angle as `position` degrees."""
        self._require_tacho()
        await self.hub.send_output(self.port, p.preset_encoder(self.port, position))

    async def set_ramp(self, acceleration_ms: int, deceleration_ms: int) -> None:
        """Set the time to ramp between 0 and 100 % speed for profiled commands."""
        port = self.port
        await self.hub.send_output(port, p.set_acceleration_time(port, acceleration_ms))
        await self.hub.send_output(port, p.set_deceleration_time(port, deceleration_ms))

    async def track_position(self, delta: int = 1) -> None:
        """Ask the hub to stream position updates for this motor."""
        self._require_tacho()
        await self.hub.subscribe(self.port, p.MOTOR_MODE_POSITION, delta)


class TechnicHub:
    """Connection to a single LEGO Technic Hub (or any LWP3 Powered Up hub).

    Example:
        async with TechnicHub() as hub:
            await hub.set_led(Color.GREEN)
            await hub.motor("A").run_for_degrees(360, 50)

    Args:
        address: Bluetooth address of the hub; None connects to the first hub found.
        name: Only connect to a hub advertising this name.
        timeout: Scan, connect and request timeout in seconds.
        write_with_response: Use acknowledged GATT writes.
    """

    def __init__(
        self,
        address: str | None = None,
        name: str | None = None,
        timeout: float = 10.0,
        write_with_response: bool = True,
    ) -> None:
        self.address = address
        self.name = name
        self.timeout = timeout
        self.write_with_response = write_with_response

        self.devices: dict[int, int] = {}
        self.port_modes: dict[int, int] = {}
        self.port_values: dict[int, bytes] = {}

        self._client: BleakClient | None = None
        self._write_lock = asyncio.Lock()
        self._disconnected = asyncio.Event()
        self._feedback: dict[int, deque[asyncio.Future[bool]]] = {}
        self._property_waiters: dict[int, list[asyncio.Future[bytes]]] = {}
        self._device_events: dict[int, asyncio.Event] = {}
        self._value_callbacks: dict[int, list[ValueCallback]] = {}
        self._background: set[asyncio.Task[None]] = set()

    # Discovery and connection

    @staticmethod
    async def scan(timeout: float = 5.0) -> list[DiscoveredHub]:
        """Find hubs that advertise within `timeout` seconds.

        Press the green button on the hub so that it is advertising.

        Args:
            timeout: Scan duration in seconds.

        Returns:
            Discovered hubs, strongest signal first.
        """
        found = await BleakScanner.discover(
            timeout=timeout, return_adv=True, service_uuids=[p.LWP_SERVICE_UUID]
        )
        hubs = []
        for device, adv in found.values():
            info = p.parse_advertisement(adv.manufacturer_data)
            hubs.append(
                DiscoveredHub(
                    address=device.address,
                    name=adv.local_name or device.name or "",
                    kind=info.hub_kind if info else "Unknown",
                    rssi=adv.rssi,
                )
            )
        return sorted(hubs, key=lambda hub: -(hub.rssi or -999))

    async def _find_device(self) -> BLEDevice:
        if self.address:
            device = await BleakScanner.find_device_by_address(
                self.address, timeout=self.timeout
            )
            if device is None:
                raise HubError(f"no hub with address {self.address} found")
            return device

        def match(device: BLEDevice, adv: AdvertisementData) -> bool:
            uuids = [uuid.lower() for uuid in adv.service_uuids]
            if p.LWP_SERVICE_UUID not in uuids:
                return False
            return self.name is None or (adv.local_name or device.name) == self.name

        device = await BleakScanner.find_device_by_filter(match, timeout=self.timeout)
        if device is None:
            raise HubError(
                f"no LEGO hub found within {self.timeout:.0f} s; "
                "press the hub button and retry"
            )
        return device

    async def connect(self) -> None:
        """Scan for the hub, connect and enable notifications.

        Raises:
            HubError: If no matching hub is found.
        """
        device = await self._find_device()
        log.info("connecting to %s (%s)", device.name, device.address)
        self._disconnected.clear()
        self._client = BleakClient(
            device, disconnected_callback=self._on_disconnect, timeout=self.timeout
        )
        await self._client.connect()
        self.address = device.address
        # The hub reports every attached device right after notifications are
        # enabled.
        await self._client.start_notify(p.LWP_CHARACTERISTIC_UUID, self._on_notify)
        await asyncio.sleep(0.5)
        log.info("connected, devices: %s", self.describe_devices())

    async def disconnect(self) -> None:
        """Close the Bluetooth connection. The hub stays switched on."""
        if self._client is not None and self._client.is_connected:
            try:
                await self._client.stop_notify(p.LWP_CHARACTERISTIC_UUID)
            except Exception:  # The link may already be gone.
                pass
            await self._client.disconnect()
        self._fail_pending(HubError("disconnected"))

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def wait_until_disconnected(self) -> None:
        """Block until the connection to the hub drops."""
        await self._disconnected.wait()

    def _on_disconnect(self, _client: BleakClient | None) -> None:
        log.warning("hub disconnected")
        self._disconnected.set()
        self._fail_pending(HubError("hub disconnected"))

    def _fail_pending(self, error: Exception) -> None:
        waiters: list[asyncio.Future] = [
            fut for queue in self._feedback.values() for fut in queue
        ]
        waiters += [fut for queue in self._property_waiters.values() for fut in queue]
        for fut in waiters:
            if not fut.done():
                fut.set_exception(error)
                # Mark as retrieved so fire and forget commands do not log
                # "exception was never retrieved".
                fut.exception()
        self._feedback.clear()
        self._property_waiters.clear()

    # Sending

    async def write(self, message: bytes) -> None:
        """Write a raw LWP3 message to the hub.

        Raises:
            HubError: If the hub is not connected.
        """
        if not self.is_connected:
            raise HubError("not connected")
        log.debug("TX %s", message.hex(" "))
        async with self._write_lock:
            await self._client.write_gatt_char(
                p.LWP_CHARACTERISTIC_UUID, message, response=self.write_with_response
            )

    async def send_output(self, port: int, message: bytes, wait: bool = False) -> bool:
        """Send a port output command that requests feedback.

        Args:
            port: Port the command addresses.
            message: Encoded port output command.
            wait: Return only after the hub reports the command finished.

        Returns:
            True when the command completed (or `wait` is False), False when a
            newer command on the same port replaced it.
        """
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        queue = self._feedback.setdefault(port, deque())
        queue.append(fut)
        try:
            await self.write(message)
        except Exception:
            queue.remove(fut)
            raise
        if not wait:
            return True
        return await fut

    async def subscribe(
        self,
        port: PortLike,
        mode: int,
        delta: int = 1,
        callback: ValueCallback | None = None,
    ) -> None:
        """Stream sensor values of a port.

        The latest raw value is kept in `port_values`.

        Args:
            port: Port to read.
            mode: Sensor mode of the attached device.
            delta: Minimum change before the hub sends an update.
            callback: Called as `callback(port, raw)` for each update; may be a
                coroutine function.
        """
        port = p.parse_port(port)
        if callback is not None:
            self._value_callbacks.setdefault(port, []).append(callback)
        self.port_modes[port] = mode
        await self.write(p.port_input_format_setup(port, mode, delta, notify=True))

    async def unsubscribe(self, port: PortLike) -> None:
        """Stop value updates for a port and drop its callbacks."""
        port = p.parse_port(port)
        mode = self.port_modes.pop(port, 0)
        self._value_callbacks.pop(port, None)
        await self.write(p.port_input_format_setup(port, mode, 1, notify=False))

    async def _request_property(self, prop: int) -> bytes:
        fut: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._property_waiters.setdefault(prop, []).append(fut)
        await self.write(p.hub_property_request(prop))
        async with asyncio.timeout(self.timeout):
            return await fut

    # High level commands

    def motor(self, port: PortLike) -> Motor:
        """Return a `Motor` for the given port ('A' to 'D')."""
        return Motor(self, p.parse_port(port))

    async def wait_for_device(self, port: PortLike, timeout: float = 5.0) -> int:
        """Wait until something is attached to a port.

        Args:
            port: Port to watch.
            timeout: Seconds to wait.

        Returns:
            The attached device type id.

        Raises:
            TimeoutError: If nothing is attached in time.
        """
        port = p.parse_port(port)
        if port not in self.devices:
            event = self._device_events.setdefault(port, asyncio.Event())
            async with asyncio.timeout(timeout):
                await event.wait()
        return self.devices[port]

    async def set_led(self, color: p.Color | int | str) -> None:
        """Set the status light to a `Color`, its index or its name."""
        if isinstance(color, str):
            color = p.Color[color.upper()]
        await self.send_output(p.PORT_LED, p.set_led_color(color))

    async def battery_level(self) -> int:
        """Return the battery charge in percent."""
        return (await self._request_property(p.HubProperty.BATTERY_VOLTAGE))[0]

    async def advertising_name(self) -> str:
        """Return the name the hub advertises."""
        raw = await self._request_property(p.HubProperty.ADVERTISING_NAME)
        return raw.decode("utf-8", "replace")

    async def firmware_version(self) -> str:
        """Return the hub firmware version as 'major.minor.bugfix.build'."""
        raw = await self._request_property(p.HubProperty.FW_VERSION)
        return format_version(int.from_bytes(raw[:4], "little"))

    async def stop_all(self, brake: bool = True) -> None:
        """Stop every attached motor."""
        motor_types = p.TACHO_MOTOR_TYPES | p.BASIC_MOTOR_TYPES
        for port, type_id in list(self.devices.items()):
            if type_id in motor_types:
                await self.motor(port).stop(brake)

    async def switch_off(self) -> None:
        """Power the hub down. The connection ends as a result."""
        await self.write(p.hub_action(p.HubAction.SWITCH_OFF))

    def describe_devices(self) -> dict[str, str]:
        """Return {port name: device name} for all attached devices."""
        return {
            p.port_name(port): p.device_name(type_id)
            for port, type_id in sorted(self.devices.items())
        }

    # Receiving

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        log.debug("RX %s", data.hex(" "))
        try:
            self._handle_message(p.parse_message(data))
        except Exception:
            log.exception("failed to handle message %s", data.hex(" "))

    def _handle_message(self, msg: p.Message) -> None:
        match msg.message_type:
            case p.MessageType.HUB_ATTACHED_IO:
                self._handle_attached_io(p.parse_attached_io(msg.payload))
            case p.MessageType.PORT_OUTPUT_COMMAND_FEEDBACK:
                for port, flags in p.parse_feedback(msg.payload).items():
                    self._handle_feedback(port, flags)
            case p.MessageType.PORT_VALUE_SINGLE:
                self._handle_port_value(msg.payload[0], msg.payload[1:])
            case p.MessageType.HUB_PROPERTIES:
                prop, operation, value = p.parse_hub_property(msg.payload)
                if operation == p.HubPropertyOperation.UPDATE:
                    for fut in self._property_waiters.pop(prop, []):
                        if not fut.done():
                            fut.set_result(value)
            case p.MessageType.GENERIC_ERROR:
                command, code = p.parse_generic_error(msg.payload)
                reason = p.HUB_ERROR_CODES.get(code, hex(code))
                log.warning("hub rejected command 0x%02X: %s", command, reason)

    def _handle_attached_io(self, info: p.AttachedIO) -> None:
        name = p.port_name(info.port)
        if info.event == p.IOEvent.DETACHED:
            log.info("port %s: device detached", name)
            self.devices.pop(info.port, None)
            self.port_values.pop(info.port, None)
            self.port_modes.pop(info.port, None)
            self._device_events.pop(info.port, None)
            return
        assert info.type_id is not None
        self.devices[info.port] = info.type_id
        log.info("port %s: %s attached", name, p.device_name(info.type_id))
        if event := self._device_events.get(info.port):
            event.set()

    def _handle_feedback(self, port: int, flags: int) -> None:
        # Commands on a port are answered in order, so the oldest waiter belongs
        # to the command the feedback refers to.
        queue = self._feedback.get(port)
        if flags & p.FEEDBACK_DISCARDED and queue:
            if not (fut := queue.popleft()).done():
                fut.set_result(False)
        if flags & p.FEEDBACK_COMPLETED and queue:
            if not (fut := queue.popleft()).done():
                fut.set_result(True)

    def _handle_port_value(self, port: int, raw: bytes) -> None:
        self.port_values[port] = raw
        for callback in self._value_callbacks.get(port, []):
            result = callback(port, raw)
            if asyncio.iscoroutine(result):
                # Keep a reference so the task is not garbage collected early.
                task = asyncio.ensure_future(result)
                self._background.add(task)
                task.add_done_callback(self._background.discard)


def format_version(value: int) -> str:
    """Decode the BCD packed LWP3 version number.

    Args:
        value: 32 bit version field.

    Returns:
        Version formatted as 'major.minor.bugfix.build'.
    """
    major = (value >> 28) & 0x07
    minor = (value >> 24) & 0x0F
    return f"{major}.{minor}.{(value >> 16) & 0xFF:02x}.{value & 0xFFFF:04x}"
