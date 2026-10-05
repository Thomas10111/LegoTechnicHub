import argparse

import pytest

from technic_hub.cli import HANDLERS, build_parser, build_shell_parser


def test_every_hub_command_has_a_handler() -> None:
    parser = build_shell_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert set(subparsers.choices) == set(HANDLERS)


def test_parse_motor_command() -> None:
    args = build_parser().parse_args(["-a", "AA:BB", "rotate", "b", "-90"])
    assert (args.address, args.command, args.port) == ("AA:BB", "rotate", 1)
    assert args.degrees == -90


def test_invalid_color_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["led", "magenta"])
