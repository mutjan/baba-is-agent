#!/usr/bin/env python3
"""Send movement keys to Baba Is You.

AppleScript/System Events can activate the app, but Baba/Chowdren does not
reliably consume those synthetic key presses as game input. By default this
wrapper uses the local CoreGraphics helper, which posts HID-level key events.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

from baba_config import load_config


KEY_CODES = {
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "undo": 6,  # z
    "z": 6,
    "restart": 15,  # r
    "r": 15,
    "confirm": 49,  # space
    "space": 49,
    "enter": 36,
    "return": 36,
    "escape": 53,
    "esc": 53,
}


ALIASES = {
    "l": "left",
    "rgt": "right",
    "r": "restart",
    "u": "up",
    "d": "down",
    "ese": "esc",
}


def parse_moves(raw: str) -> list[str]:
    moves: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        token = chunk.strip().lower()
        if not token:
            continue
        if "*" in token:
            name, count = token.split("*", 1)
        else:
            name, count = token, "1"
        name = ALIASES.get(name, name)
        if name not in KEY_CODES:
            valid = ", ".join(sorted(KEY_CODES))
            raise SystemExit(f"Unknown move '{name}'. Valid moves: {valid}")
        try:
            repeat = int(count)
        except ValueError as exc:
            raise SystemExit(f"Invalid repeat count in '{token}'") from exc
        if repeat < 1:
            raise SystemExit(f"Repeat count must be positive in '{token}'")
        moves.extend([name] * repeat)
    return moves


def activate_game(app_name: str) -> None:
    subprocess.run(
        ["osascript", "-e", f'tell application "{app_name}" to activate'],
        check=True,
    )


def send_key_code(key_code: int) -> None:
    subprocess.run(
        [
            "osascript",
            "-e",
            f'tell application "System Events" to key code {key_code}',
        ],
        check=True,
    )


def ensure_cgevent_helper() -> Path:
    root = Path(__file__).resolve().parent
    source = root / "baba_cgevent_keys.c"
    binary = root / "baba_cgevent_keys"
    if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
        return binary
    subprocess.run(
        [
            "clang",
            "-Wall",
            "-Wextra",
            "-framework",
            "ApplicationServices",
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
    )
    return binary


def send_with_cgevent(moves: list[str], delay: float, hold_ms: int) -> None:
    binary = ensure_cgevent_helper()
    subprocess.run(
        [str(binary), "--delay-ms", str(int(delay * 1000)), "--hold-ms", str(hold_ms), *moves],
        check=True,
    )


def frontmost_process() -> str:
    result = subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to name of first process whose frontmost is true',
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def observe_command(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "baba_try.py"
    command = [sys.executable, str(script), args.moves]
    display = ["python3", "scripts/baba_try.py", args.moves]

    if args.config:
        command.extend(["--config", str(args.config)])
        display.extend(["--config", str(args.config)])
    if args.app_name:
        command.extend(["--app-name", args.app_name])
        display.extend(["--app-name", args.app_name])
    if args.observe_timeout is not None:
        command.extend(["--timeout", str(args.observe_timeout)])
        display.extend(["--timeout", str(args.observe_timeout)])
    if args.delay is not None:
        command.extend(["--delay", str(args.delay)])
        display.extend(["--delay", str(args.delay)])
    command.extend(["--hold-ms", str(args.hold_ms)])
    display.extend(["--hold-ms", str(args.hold_ms)])
    command.extend(["--method", args.method])
    display.extend(["--method", args.method])
    if args.no_activate:
        command.append("--no-activate")
        display.append("--no-activate")
    command.extend(["--pre-delay", str(args.pre_delay)])
    display.extend(["--pre-delay", str(args.pre_delay)])
    if args.focus:
        command.extend(["--focus", args.focus])
        display.extend(["--focus", args.focus])
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
        display.extend(["--limit", str(args.limit)])
    return command, display


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "moves",
        help="Comma-separated moves, e.g. 'right*8' or 'right,right,up'",
    )
    parser.add_argument(
        "--delay",
        type=float,
        help="Delay between keys. Defaults to input_delay in baba_config.json.",
    )
    parser.add_argument(
        "--hold-ms",
        type=int,
        default=90,
        help="Milliseconds to hold each key when using the cgevent method",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print without sending")
    parser.add_argument(
        "--method",
        choices=["cgevent", "applescript"],
        default="cgevent",
        help="Key injection method. cgevent is the verified Baba input path.",
    )
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Do not activate Baba Is You before sending keys",
    )
    parser.add_argument(
        "--pre-delay",
        type=float,
        default=0.15,
        help="Delay after activating Baba Is You before sending the first key",
    )
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--app-name", help="Override configured macOS app name")
    parser.add_argument(
        "--observe",
        action="store_true",
        help="Delegate to baba_try.py so the real key input is followed by a state delta",
    )
    parser.add_argument(
        "--observe-timeout",
        type=float,
        default=3.0,
        help="Seconds baba_try.py waits for state refreshes when --observe is used",
    )
    parser.add_argument(
        "--focus",
        help="With --observe, comma-separated unit names to show in the delta, such as baba,text_is,flag",
    )
    parser.add_argument("--limit", type=int, default=20, help="With --observe, limit changed units per category")
    args = parser.parse_args()

    moves = parse_moves(args.moves)
    print("moves=" + ",".join(moves))

    if args.observe:
        command, display = observe_command(args)
        print("observe=delegate_to_baba_try")
        print("command=" + shlex.join(display))
        if args.dry_run:
            return 0
        return subprocess.run(command, cwd=Path(__file__).resolve().parents[1], check=False).returncode

    if args.dry_run:
        return 0

    config = load_config(args.config)
    app_name = args.app_name or config.app_name
    delay = args.delay if args.delay is not None else config.input_delay

    if not args.no_activate:
        activate_game(app_name)
        time.sleep(args.pre_delay)

    if args.method == "cgevent":
        send_with_cgevent(moves, delay, args.hold_ms)
    else:
        for move in moves:
            send_key_code(KEY_CODES[move])
            time.sleep(delay)

    print("frontmost=" + frontmost_process())
    return 0


if __name__ == "__main__":
    sys.exit(main())
