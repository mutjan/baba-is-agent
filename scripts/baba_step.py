#!/usr/bin/env python3
"""Send Baba Is You moves one at a time, waiting for live exported state."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from baba_config import load_config
from baba_send_keys import (
    KEY_CODES,
    activate_game,
    frontmost_process,
    parse_moves,
    send_key_code,
    send_with_cgevent,
)
from read_baba_state import current_save_file, load_state, summarize


def state_path(save_dir: Path, override: Path | None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    return (save_dir / "codex_state.json").expanduser().resolve()


def current_state_mtime(path: Path, save_dir: Path) -> float | None:
    if path.exists():
        return path.stat().st_mtime
    save_file = current_save_file(save_dir)
    if save_file.exists():
        return save_file.stat().st_mtime
    return None


def send_one(move: str, *, method: str, delay: float, hold_ms: int) -> None:
    if method == "cgevent":
        send_with_cgevent([move], delay, hold_ms)
    else:
        send_key_code(KEY_CODES[move])
        time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("moves", help="Comma-separated moves, e.g. 'right,up,left'")
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--app-name", help="Override configured macOS app name")
    parser.add_argument("--state-path", type=Path, help="Override legacy JSON state path")
    parser.add_argument("--timeout", type=float, default=3.0, help="Seconds to wait after each move")
    parser.add_argument(
        "--delay",
        type=float,
        help="Delay after each key press. Defaults to input_delay in baba_config.json.",
    )
    parser.add_argument("--hold-ms", type=int, default=90, help="Milliseconds to hold each cgevent key")
    parser.add_argument(
        "--method",
        choices=["cgevent", "applescript"],
        default="cgevent",
        help="Key injection method. cgevent is the verified Baba input path.",
    )
    parser.add_argument("--no-activate", action="store_true", help="Do not activate Baba before sending")
    parser.add_argument("--pre-delay", type=float, default=0.15, help="Delay after activating Baba")
    parser.add_argument("--dry-run", action="store_true", help="Print moves and state path without sending")
    parser.add_argument("--no-wait-state", action="store_true", help="Send moves without waiting for live state")
    parser.add_argument("--json", action="store_true", help="Print the final state as JSON")
    parser.add_argument("--limit", type=int, default=12, help="Limit printed rule/object groups")
    args = parser.parse_args()

    moves = parse_moves(args.moves)
    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    app_name = args.app_name or config.app_name
    delay = args.delay if args.delay is not None else config.input_delay
    live_state_path = state_path(save_dir, args.state_path)

    print("moves=" + ",".join(moves))
    print(f"state_path={live_state_path}")
    print(f"save_state_path={current_save_file(save_dir)}")

    if args.dry_run:
        return 0

    if not args.no_activate:
        activate_game(app_name)
        time.sleep(args.pre_delay)

    latest_state = None
    for index, move in enumerate(moves, start=1):
        before = current_state_mtime(live_state_path, save_dir)
        send_one(move, method=args.method, delay=delay, hold_ms=args.hold_ms)
        print(f"sent={index}/{len(moves)} move={move}")

        if args.no_wait_state:
            time.sleep(delay)
            continue

        latest_state = load_state(
            live_state_path,
            wait=True,
            timeout=args.timeout,
            since_mtime=before,
            save_dir=save_dir,
        )
        meta = latest_state.get("meta", {})
        print(
            "updated="
            f"turn={meta.get('turn')} seq={meta.get('sequence')} "
            f"source={meta.get('source')} last_command={meta.get('last_command')}"
        )

    print("frontmost=" + frontmost_process())

    if latest_state is not None:
        print()
        if args.json:
            print(json.dumps(latest_state, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            summarize(latest_state, live_state_path, limit=args.limit)

    return 0


if __name__ == "__main__":
    sys.exit(main())
