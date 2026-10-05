"""LEGO Wireless Protocol 3.0 (LWP3) message encoding and decoding.

This module is pure Python with no Bluetooth dependency, so it can be unit tested on
any machine. Reference: https://lego.github.io/lego-ble-wireless-protocol-docs/
"""

import struct
from dataclasses import dataclass
from enum import IntEnum

# GATT identifiers shared by all Powered Up hubs (Technic Hub 88012, City Hub,
# BOOST Move Hub, ...).
LWP_SERVICE_UUID = "00001623-1212-efde-1623-785feabcd123"
LWP_CHARACTERISTIC_UUID = "00001624-1212-efde-1623-785feabcd123"

# Bluetooth SIG company identifier of the LEGO System A/S.
LEGO_MANUFACTURER_ID = 0x0397

HUB_ID = 0x00


class MessageType(IntEnum):
    HUB_PROPERTIES = 0x01
    HUB_ACTIONS = 0x02
    HUB_ALERTS = 0x03
    HUB_ATTACHED_IO = 0x04
    GENERIC_ERROR = 0x05
    PORT_INPUT_FORMAT_SETUP_SINGLE = 0x41
    PORT_VALUE_SINGLE = 0x45
    PORT_INPUT_FORMAT_SINGLE = 0x47
    PORT_OUTPUT_COMMAND = 0x81
    PORT_OUTPUT_COMMAND_FEEDBACK = 0x82


class HubProperty(IntEnum):
    ADVERTISING_NAME = 0x01
    BUTTON = 0x02
    FW_VERSION = 0x03
    HW_VERSION = 0x04
    RSSI = 0x05
    BATTERY_VOLTAGE = 0x06
    BATTERY_TYPE = 0x07
    MANUFACTURER_NAME = 0x08
    PRIMARY_MAC_ADDRESS = 0x0D


class HubPropertyOperation(IntEnum):
    SET = 0x01
    ENABLE_UPDATES = 0x02
    DISABLE_UPDATES = 0x03
    RESET = 0x04
    REQUEST_UPDATE = 0x05
    UPDATE = 0x06


class HubAction(IntEnum):
    SWITCH_OFF = 0x01
    DISCONNECT = 0x02


class IOEvent(IntEnum):
    DETACHED = 0x00
    ATTACHED = 0x01
    ATTACHED_VIRTUAL = 0x02


class OutputSubCommand(IntEnum):
    SET_ACC_TIME = 0x05
    SET_DEC_TIME = 0x06
    START_SPEED = 0x07
    START_SPEED_FOR_TIME = 0x09
    START_SPEED_FOR_DEGREES = 0x0B
    GOTO_ABSOLUTE_POSITION = 0x0D
    WRITE_DIRECT_MODE_DATA = 0x51


class EndState(IntEnum):
    """What a motor does after a timed or positional command finishes."""

    FLOAT = 0
    HOLD = 126
    BRAKE = 127


class Color(IntEnum):
    """Color indices understood by the hub's built in RGB status light."""

    OFF = 0
    PINK = 1
    PURPLE = 2
    BLUE = 3
    LIGHT_BLUE = 4
    CYAN = 5
    GREEN = 6
    YELLOW = 7
    ORANGE = 8
    RED = 9
    WHITE = 10


# Startup and completion byte of a port output command.
STARTUP_IMMEDIATE = 0x10
COMPLETION_FEEDBACK = 0x01

# Bits of the port output command feedback byte.
FEEDBACK_IN_PROGRESS = 0x01
FEEDBACK_COMPLETED = 0x02
FEEDBACK_DISCARDED = 0x04
FEEDBACK_IDLE = 0x08
FEEDBACK_BUSY = 0x10

# Special power values for raw power commands.
POWER_FLOAT = 0
POWER_BRAKE = 127

# Ports of the Technic Hub (88012).
TECHNIC_HUB_PORTS: dict[str, int] = {"A": 0x00, "B": 0x01, "C": 0x02, "D": 0x03}
PORT_LED = 0x32
PORT_CURRENT = 0x3B
PORT_VOLTAGE = 0x3C
PORT_TEMPERATURE = 0x3D
PORT_ACCELEROMETER = 0x61
PORT_GYRO = 0x62
PORT_TILT = 0x63

# Attached device type identifiers (subset relevant for Technic builds).
DEVICE_TYPES: dict[int, str] = {
    0x0001: "Medium Motor",
    0x0002: "Train Motor",
    0x0008: "Light",
    0x0014: "Voltage Sensor",
    0x0015: "Current Sensor",
    0x0016: "Piezo Tone",
    0x0017: "RGB Light",
    0x0022: "WeDo 2.0 Tilt Sensor",
    0x0023: "WeDo 2.0 Motion Sensor",
    0x0025: "Color & Distance Sensor",
    0x0026: "BOOST Interactive Motor",
    0x0027: "BOOST Move Hub Motor",
    0x002E: "Technic Large Motor",
    0x002F: "Technic XL Motor",
    0x0030: "Technic Medium Angular Motor",
    0x0031: "Technic Large Angular Motor",
    0x0036: "Technic Hub Gesture Sensor",
    0x0037: "Remote Control Button",
    0x0038: "Remote Control RSSI",
    0x0039: "Technic Hub Accelerometer",
    0x003A: "Technic Hub Gyro Sensor",
    0x003B: "Technic Hub Tilt Sensor",
    0x003C: "Technic Hub Temperature Sensor",
    0x003D: "Technic Color Sensor",
    0x003E: "Technic Distance Sensor",
    0x003F: "Technic Force Sensor",
    0x0041: "Technic Small Angular Motor",
    0x004B: "Technic Medium Angular Motor (grey)",
    0x004C: "Technic Large Angular Motor (grey)",
}

# Motors with an internal rotation sensor. They support speed regulation, rotating
# by degrees and absolute positioning.
TACHO_MOTOR_TYPES = frozenset(
    {0x0026, 0x0027, 0x002E, 0x002F, 0x0030, 0x0031, 0x0041, 0x004B, 0x004C}
)

# Motors without a rotation sensor. They only accept raw power.
BASIC_MOTOR_TYPES = frozenset({0x0001, 0x0002})

# Sensor mode that reports the cumulative position in degrees on tacho motors.
MOTOR_MODE_POSITION = 0x02

# System type byte in the advertisement manufacturer data.
HUB_SYSTEM_TYPES: dict[int, str] = {
    0x20: "DUPLO Train Base",
    0x40: "BOOST Move Hub",
    0x41: "City Hub",
    0x42: "Remote Control",
    0x80: "Technic Hub",
    0x83: "SPIKE Essential Hub",
    0x84: "SPIKE Prime Hub",
}

HUB_ERROR_CODES: dict[int, str] = {
    0x01: "ACK",
    0x02: "MACK",
    0x03: "Buffer overflow",
    0x04: "Timeout",
    0x05: "Command not recognized",
    0x06: "Invalid use",
    0x07: "Overcurrent",
    0x08: "Internal error",
}


def device_name(type_id: int) -> str:
    """Return a readable name for an attached device type id."""
    return DEVICE_TYPES.get(type_id, f"Unknown device 0x{type_id:04X}")


def port_name(port: int) -> str:
    """Return 'A' to 'D' for the external ports, hex for internal ones."""
    for name, number in TECHNIC_HUB_PORTS.items():
        if number == port:
            return name
    return f"0x{port:02X}"


def parse_port(value: str | int) -> int:
    """Convert a port given as 'A' to 'D', a decimal or a 0x hex number.

    Args:
        value: Port letter, number or numeric string.

    Returns:
        The LWP3 port id.
    """
    if isinstance(value, int):
        return value
    text = value.strip().upper()
    if text in TECHNIC_HUB_PORTS:
        return TECHNIC_HUB_PORTS[text]
    return int(text, 0)


def clamp(value: int, low: int, high: int) -> int:
    """Limit `value` to the closed interval [low, high]."""
    return max(low, min(high, int(value)))


# Encoding


def frame(message_type: int, payload: bytes = b"") -> bytes:
    """Prefix a payload with the LWP3 common header.

    Args:
        message_type: One of `MessageType`.
        payload: Message body after the header.

    Returns:
        The complete message ready to write to the hub characteristic.
    """
    length = len(payload) + 3
    if length < 128:
        return bytes([length, HUB_ID, message_type]) + payload
    # Messages of 128 bytes and more use a two byte length field.
    length += 1
    header = bytes([(length & 0x7F) | 0x80, length >> 7, HUB_ID, message_type])
    return header + payload


def hub_property_request(
    prop: int, operation: int = HubPropertyOperation.REQUEST_UPDATE
) -> bytes:
    """Build a hub property message (by default: request the current value)."""
    return frame(MessageType.HUB_PROPERTIES, bytes([prop, operation]))


def hub_action(action: int) -> bytes:
    """Build a hub action message such as switching the hub off."""
    return frame(MessageType.HUB_ACTIONS, bytes([action]))


def port_input_format_setup(
    port: int, mode: int, delta: int = 1, notify: bool = True
) -> bytes:
    """Build a message that selects a sensor mode and enables value updates.

    Args:
        port: Port id.
        mode: Sensor mode of the attached device.
        delta: Minimum change of the value before the hub sends an update.
        notify: Whether the hub should push updates.

    Returns:
        The encoded message.
    """
    payload = bytes([port, mode]) + struct.pack("<IB", delta, int(notify))
    return frame(MessageType.PORT_INPUT_FORMAT_SETUP_SINGLE, payload)


def port_output(
    port: int, subcommand: int, data: bytes, feedback: bool = True
) -> bytes:
    """Build a port output command that executes immediately.

    Args:
        port: Port id.
        subcommand: One of `OutputSubCommand`.
        data: Subcommand parameters.
        feedback: Ask the hub to report when the command completes.

    Returns:
        The encoded message.
    """
    flags = STARTUP_IMMEDIATE | (COMPLETION_FEEDBACK if feedback else 0)
    payload = bytes([port, flags, subcommand]) + data
    return frame(MessageType.PORT_OUTPUT_COMMAND, payload)


def _profile(use_profile: bool) -> int:
    # Bit 0 selects the acceleration profile, bit 1 the deceleration profile.
    return 0x03 if use_profile else 0x00


def start_power(port: int, power: int, feedback: bool = True) -> bytes:
    """Unregulated power from -100 to 100. 0 lets the motor float, 127 brakes."""
    if power not in (POWER_FLOAT, POWER_BRAKE):
        power = clamp(power, -100, 100)
    data = bytes([0x00]) + struct.pack("<b", power)
    return port_output(port, OutputSubCommand.WRITE_DIRECT_MODE_DATA, data, feedback)


def start_speed(
    port: int,
    speed: int,
    max_power: int = 100,
    use_profile: bool = True,
    feedback: bool = True,
) -> bytes:
    """Run a tacho motor continuously at a regulated speed from -100 to 100."""
    data = struct.pack(
        "<bBB",
        clamp(speed, -100, 100),
        clamp(max_power, 0, 100),
        _profile(use_profile),
    )
    return port_output(port, OutputSubCommand.START_SPEED, data, feedback)


def start_speed_for_time(
    port: int,
    time_ms: int,
    speed: int,
    max_power: int = 100,
    end_state: int = EndState.BRAKE,
    use_profile: bool = True,
    feedback: bool = True,
) -> bytes:
    """Run a tacho motor for `time_ms` milliseconds, then apply `end_state`."""
    data = struct.pack(
        "<HbBBB",
        clamp(time_ms, 0, 0xFFFF),
        clamp(speed, -100, 100),
        clamp(max_power, 0, 100),
        end_state,
        _profile(use_profile),
    )
    return port_output(port, OutputSubCommand.START_SPEED_FOR_TIME, data, feedback)


def start_speed_for_degrees(
    port: int,
    degrees: int,
    speed: int,
    max_power: int = 100,
    end_state: int = EndState.BRAKE,
    use_profile: bool = True,
    feedback: bool = True,
) -> bytes:
    """Rotate a tacho motor by `degrees`; negative degrees reverse direction."""
    # The hub expects positive degrees; direction comes from the speed sign.
    if degrees < 0:
        degrees, speed = -degrees, -speed
    data = struct.pack(
        "<ibBBB",
        clamp(degrees, 0, 0x7FFFFFFF),
        clamp(speed, -100, 100),
        clamp(max_power, 0, 100),
        end_state,
        _profile(use_profile),
    )
    return port_output(port, OutputSubCommand.START_SPEED_FOR_DEGREES, data, feedback)


def goto_absolute_position(
    port: int,
    position: int,
    speed: int,
    max_power: int = 100,
    end_state: int = EndState.HOLD,
    use_profile: bool = True,
    feedback: bool = True,
) -> bytes:
    """Move a tacho motor to `position` degrees relative to its zero point."""
    data = struct.pack(
        "<ibBBB",
        int(position),
        clamp(abs(speed), 0, 100),
        clamp(max_power, 0, 100),
        end_state,
        _profile(use_profile),
    )
    return port_output(port, OutputSubCommand.GOTO_ABSOLUTE_POSITION, data, feedback)


def set_acceleration_time(port: int, time_ms: int, feedback: bool = True) -> bytes:
    """Set the time to ramp from 0 to 100 % speed for profiled commands."""
    data = struct.pack("<HB", clamp(time_ms, 0, 10000), 0x00)
    return port_output(port, OutputSubCommand.SET_ACC_TIME, data, feedback)


def set_deceleration_time(port: int, time_ms: int, feedback: bool = True) -> bytes:
    """Set the time to ramp from 100 to 0 % speed for profiled commands."""
    data = struct.pack("<HB", clamp(time_ms, 0, 10000), 0x00)
    return port_output(port, OutputSubCommand.SET_DEC_TIME, data, feedback)


def preset_encoder(port: int, position: int = 0, feedback: bool = True) -> bytes:
    """Redefine the current motor position as `position` degrees."""
    data = bytes([MOTOR_MODE_POSITION]) + struct.pack("<i", int(position))
    return port_output(port, OutputSubCommand.WRITE_DIRECT_MODE_DATA, data, feedback)


def set_led_color(color: int, port: int = PORT_LED, feedback: bool = True) -> bytes:
    """Set the hub status light to one of the `Color` indices."""
    data = bytes([0x00, clamp(color, 0, 10)])
    return port_output(port, OutputSubCommand.WRITE_DIRECT_MODE_DATA, data, feedback)


# Decoding


@dataclass
class Message:
    message_type: int
    payload: bytes


@dataclass
class AttachedIO:
    port: int
    event: int
    type_id: int | None = None
    # Only set for virtual ports, which combine two physical ports.
    port_a: int | None = None
    port_b: int | None = None


@dataclass
class AdvertisementInfo:
    system_type: int
    hub_kind: str
    button_pressed: bool


def parse_message(data: bytes | bytearray) -> Message:
    """Split a raw notification into message type and payload.

    Args:
        data: Bytes received from the hub characteristic.

    Returns:
        The parsed message.

    Raises:
        ValueError: If the data is empty or shorter than its length field says.
    """
    data = bytes(data)
    if not data:
        raise ValueError("empty message")
    if data[0] & 0x80:
        length, header = (data[0] & 0x7F) | (data[1] << 7), 2
    else:
        length, header = data[0], 1
    if len(data) < length:
        raise ValueError(f"truncated message: expected {length} bytes, got {len(data)}")
    # Skip the hub id byte.
    return Message(message_type=data[header + 1], payload=data[header + 2 : length])


def parse_attached_io(payload: bytes) -> AttachedIO:
    """Decode a Hub Attached I/O payload."""
    info = AttachedIO(port=payload[0], event=payload[1])
    if info.event in (IOEvent.ATTACHED, IOEvent.ATTACHED_VIRTUAL):
        info.type_id = struct.unpack_from("<H", payload, 2)[0]
    if info.event == IOEvent.ATTACHED_VIRTUAL:
        info.port_a, info.port_b = payload[4], payload[5]
    return info


def parse_feedback(payload: bytes) -> dict[int, int]:
    """Return {port: feedback flags}; one message may report several ports."""
    return {payload[i]: payload[i + 1] for i in range(0, len(payload) - 1, 2)}


def parse_hub_property(payload: bytes) -> tuple[int, int, bytes]:
    """Return (property, operation, value) of a hub property payload."""
    return payload[0], payload[1], payload[2:]


def parse_generic_error(payload: bytes) -> tuple[int, int]:
    """Return (command type that failed, error code)."""
    return payload[0], payload[1]


def parse_advertisement(
    manufacturer_data: dict[int, bytes],
) -> AdvertisementInfo | None:
    """Decode the LEGO manufacturer data of a BLE advertisement.

    Args:
        manufacturer_data: Mapping of company id to data, as reported by bleak.

    Returns:
        Hub information, or None if the advertisement is not from a LEGO hub.
    """
    data = manufacturer_data.get(LEGO_MANUFACTURER_ID)
    if data is None or len(data) < 2:
        return None
    system_type = data[1]
    return AdvertisementInfo(
        system_type=system_type,
        hub_kind=HUB_SYSTEM_TYPES.get(system_type, f"Unknown hub 0x{system_type:02X}"),
        button_pressed=bool(data[0]),
    )


def decode_int(data: bytes) -> int:
    """Decode a little endian signed value of 1, 2 or 4 bytes."""
    match len(data):
        case 1:
            fmt = "<b"
        case 2:
            fmt = "<h"
        case 4:
            fmt = "<i"
        case size:
            raise ValueError(f"cannot decode {size} byte value")
    return struct.unpack(fmt, data)[0]


def decode_int16_list(data: bytes) -> tuple[int, ...]:
    """Decode consecutive little endian int16 values (for example x, y, z)."""
    count = len(data) // 2
    return struct.unpack(f"<{count}h", data[: count * 2])
