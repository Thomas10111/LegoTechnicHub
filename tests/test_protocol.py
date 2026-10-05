import pytest

from technic_hub import protocol as p


def h(text: str) -> bytes:
    return bytes.fromhex(text)


def test_start_power() -> None:
    assert p.start_power(0, 50) == h("08 00 81 00 11 51 00 32")
    assert p.start_power(1, -100) == h("08 00 81 01 11 51 00 9c")


def test_start_power_clamps_but_keeps_brake() -> None:
    assert p.start_power(0, 500)[-1] == 100
    assert p.start_power(0, p.POWER_BRAKE)[-1] == 127


def test_start_power_without_feedback() -> None:
    assert p.start_power(0, 10, feedback=False)[4] == 0x10


def test_start_speed() -> None:
    assert p.start_speed(2, -30, 80) == h("09 00 81 02 11 07 e2 50 03")


def test_start_speed_for_degrees() -> None:
    expected = h("0e 00 81 00 11 0b 5a 00 00 00 32 64 7f 03")
    assert p.start_speed_for_degrees(0, 90, 50) == expected


def test_negative_degrees_reverse_speed() -> None:
    msg = p.start_speed_for_degrees(0, -90, 50)
    assert msg[6:10] == h("5a 00 00 00")
    assert msg[10] == 0xCE  # -50


def test_start_speed_for_time() -> None:
    expected = h("0c 00 81 03 11 09 e8 03 28 64 7f 03")
    assert p.start_speed_for_time(3, 1000, 40) == expected


def test_goto_absolute_position() -> None:
    expected = h("0e 00 81 01 11 0d 4c ff ff ff 3c 64 7e 03")
    assert p.goto_absolute_position(1, -180, 60) == expected


def test_preset_encoder() -> None:
    assert p.preset_encoder(0, 0) == h("0b 00 81 00 11 51 02 00 00 00 00")


def test_led_color() -> None:
    assert p.set_led_color(p.Color.RED) == h("08 00 81 32 11 51 00 09")


def test_hub_messages() -> None:
    battery = p.hub_property_request(p.HubProperty.BATTERY_VOLTAGE)
    assert battery == h("05 00 01 06 05")
    assert p.hub_action(p.HubAction.SWITCH_OFF) == h("04 00 02 01")


def test_port_input_format_setup() -> None:
    expected = h("0a 00 41 00 02 01 00 00 00 01")
    assert p.port_input_format_setup(0, 2, 1, True) == expected


def test_long_frame_uses_two_length_bytes() -> None:
    msg = p.frame(0x01, bytes(200))
    parsed = p.parse_message(msg)
    assert len(msg) == 204
    assert parsed.message_type == 0x01
    assert parsed.payload == bytes(200)


def test_parse_attached_io() -> None:
    msg = p.parse_message(h("0f 00 04 00 01 2e 00 00 10 00 00 00 10 00 00"))
    info = p.parse_attached_io(msg.payload)
    assert (info.port, info.event, info.type_id) == (0, p.IOEvent.ATTACHED, 0x2E)
    assert p.device_name(0x2E) == "Technic Large Motor"


def test_parse_virtual_port() -> None:
    msg = p.parse_message(h("09 00 04 10 02 2e 00 00 01"))
    info = p.parse_attached_io(msg.payload)
    assert (info.port, info.port_a, info.port_b) == (0x10, 0, 1)


def test_parse_feedback_multiple_ports() -> None:
    msg = p.parse_message(h("07 00 82 00 0a 01 01"))
    assert p.parse_feedback(msg.payload) == {0: 0x0A, 1: 0x01}


def test_parse_truncated_message() -> None:
    with pytest.raises(ValueError):
        p.parse_message(h("08 00 81 00"))


@pytest.mark.parametrize(
    ("value", "port"), [("a", 0), ("D", 3), ("0x32", 0x32), ("50", 50), (2, 2)]
)
def test_parse_port(value: str | int, port: int) -> None:
    assert p.parse_port(value) == port


def test_parse_advertisement() -> None:
    info = p.parse_advertisement({p.LEGO_MANUFACTURER_ID: h("00 80 06 00 41 00")})
    assert info is not None and info.hub_kind == "Technic Hub"
    assert p.parse_advertisement({0x004C: b"\x01\x02"}) is None


def test_decode_values() -> None:
    assert p.decode_int(h("f6 ff ff ff")) == -10
    assert p.decode_int(h("85")) == -123
    assert p.decode_int16_list(h("01 00 ff ff 05 00")) == (1, -1, 5)
    with pytest.raises(ValueError):
        p.decode_int(h("01 02 03"))
