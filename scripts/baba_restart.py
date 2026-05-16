#!/usr/bin/env python3
"""Restart the current Baba Is You level or world-map position.

Baba uses the same confirmation flow in levels and on the world map:
restart, move selection down to YES, then enter.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from baba_config import load_config
from baba_loop_guard import record_action


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
RUNS_ROOT = PROJECT_ROOT / "runs"
RESTART_MOVES = "r,down,enter"
ROUTE_PLAN_NAME = "baba_route_plan.md"


def route_plan_path(config_path: Path | None) -> Path | None:
    try:
        config = load_config(config_path, refresh_status=False)
    except SystemExit:
        return None
    run_id = (config.current_run_id or "").strip()
    if not re.fullmatch(r"\d{3}_[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        return None
    path = RUNS_ROOT / run_id / ROUTE_PLAN_NAME
    return path if path.exists() else None


def last_action_check_status(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    matches = list(re.finditer(r"(?ms)^## .+? action_check\n\n(?P<body>.*?)(?=^## |\Z)", text))
    if not matches:
        return None
    body = matches[-1].group("body")
    match = re.search(r"(?m)^- check: (pass|fail)\s*$", body)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay",
        type=float,
        help="Delay between keys. Defaults to input_delay in baba_config.json.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print without sending")
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--force", action="store_true", help="Restart even when the route plan shows preserved progress.")
    parser.add_argument("--app-name", help="Override configured macOS app name")
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Do not activate Baba Is You before sending keys",
    )
    args = parser.parse_args()

    plan_path = route_plan_path(args.config)
    last_status = last_action_check_status(plan_path)
    if last_status == "pass" and not args.force:
        print("restart_guard=preserved_progress")
        print("reason=last action_check passed; restart would discard verified progress")
        if plan_path:
            print(f"route_plan={plan_path}")
        print("allowed_next=python3 scripts/read_baba_state.py --limit 60")
        print("allowed_next=python3 scripts/baba_action_check.py '<short moves>' --expect-moved-delta '<unit-or-text>:<dir>'")
        print("force_next=python3 scripts/baba_restart.py --force")
        return 2

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
    if not args.dry_run:
        guard_path = record_action("restart", args.config, detail=RESTART_MOVES)
        if guard_path:
            print(f"loop_guard=reset path={guard_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
