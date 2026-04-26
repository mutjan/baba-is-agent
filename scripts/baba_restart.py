#!/usr/bin/env python3
"""Restart the current Baba Is You level or world-map position.

Baba uses the same confirmation flow in levels and on the world map:
restart, move selection down to YES, then enter.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESTART_MOVES = "r,down,enter"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay",
        type=float,
        help="Delay between keys. Defaults to input_delay in baba_config.json.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print without sending")
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--app-name", help="Override configured macOS app name")
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Do not activate Baba Is You before sending keys",
    )
    args = parser.parse_args()

    command = [
        sys.executable,
        str(ROOT / "baba_send_keys.py"),
        RESTART_MOVES,
    ]
    if args.delay is not None:
        command.extend(["--delay", str(args.delay)])
    if args.dry_run:
        command.append("--dry-run")
    if args.config:
        command.extend(["--config", str(args.config)])
    if args.app_name:
        command.extend(["--app-name", args.app_name])
    if args.no_activate:
        command.append("--no-activate")

    print("restart_moves=" + RESTART_MOVES)
    print("command=" + " ".join(command))
    subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
