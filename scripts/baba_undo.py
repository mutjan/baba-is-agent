#!/usr/bin/env python3
"""Undo recent Baba Is You turns with z and print the observed state delta."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def add_optional(command: list[str], flag: str, value: object | None) -> None:
    if value is not None:
        command.extend([flag, str(value)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=1, help="Number of z undo presses to send.")
    parser.add_argument(
        "--allow-multi-step",
        action="store_true",
        help="Permit more than one undo press. Benchmark agents should avoid this unless a user explicitly asks.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print command without sending keys.")
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--app-name", help="Override configured macOS app name")
    parser.add_argument("--timeout", type=float, default=3.0, help="Seconds to wait for observed state refreshes.")
    parser.add_argument("--delay", type=float, help="Delay after each key press.")
    parser.add_argument("--hold-ms", type=int, help="Milliseconds to hold each key.")
    parser.add_argument("--method", choices=["cgevent", "applescript"], default="cgevent")
    parser.add_argument("--no-activate", action="store_true", help="Do not activate Baba before sending.")
    parser.add_argument("--pre-delay", type=float, help="Delay after activating Baba.")
    parser.add_argument("--focus", help="Comma-separated unit names to show in the observed delta.")
    parser.add_argument("--limit", type=int, default=20, help="Limit printed changed units per category.")
    args = parser.parse_args()

    if args.steps < 1:
        print("undo=error")
        print("reason=--steps must be positive")
        return 2
    if args.steps > 1 and not args.allow_multi_step:
        print("undo=error")
        print("reason=multi-step undo is unsafe because blocked/no-op inputs can make z*N erase earlier successful progress")
        print(f"requested_steps={args.steps}")
        print("allowed_next=python3 scripts/read_baba_state.py --limit 60")
        print("allowed_next=python3 scripts/baba_undo.py --steps 1")
        print("override=add --allow-multi-step only for explicit manual rollback/debugging")
        return 2

    moves = "z" if args.steps == 1 else f"z*{args.steps}"
    command = [
        sys.executable,
        str(SCRIPTS_DIR / "baba_send_keys.py"),
        moves,
        "--observe",
        "--observe-timeout",
        str(args.timeout),
        "--method",
        args.method,
        "--limit",
        str(args.limit),
    ]
    add_optional(command, "--config", args.config)
    add_optional(command, "--app-name", args.app_name)
    add_optional(command, "--delay", args.delay)
    add_optional(command, "--hold-ms", args.hold_ms)
    add_optional(command, "--pre-delay", args.pre_delay)
    add_optional(command, "--focus", args.focus)
    if args.no_activate:
        command.append("--no-activate")
    if args.dry_run:
        command.append("--dry-run")

    print(f"undo_steps={args.steps}", flush=True)
    print(f"moves={moves}", flush=True)
    print("score_note=undo restores board state but live-state turn may not decrease", flush=True)
    if args.steps > 1:
        print("undo_warning=multi-step undo can overshoot if the failed segment had blocked/no-op inputs", flush=True)
    print(
        "command="
        + shlex.join(["python3", "scripts/baba_send_keys.py", moves, *command[3:]]),
        flush=True,
    )
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
