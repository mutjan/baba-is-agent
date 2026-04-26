#!/usr/bin/env python3
"""Read the latest JSON emitted by the Baba Is You Lua state exporter."""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path
from typing import Any

from baba_config import load_config


def state_path_from_args(args: argparse.Namespace) -> Path:
    if args.path:
        return args.path.expanduser().resolve()
    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    return (save_dir / "codex_state.json").expanduser().resolve()


def load_state(path: Path, *, wait: bool, timeout: float, since_mtime: float | None) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        if path.exists():
            stat = path.stat()
            if since_mtime is None or stat.st_mtime > since_mtime:
                return json.loads(path.read_text(encoding="utf-8"))
        if not wait or time.monotonic() >= deadline:
            if not path.exists():
                raise SystemExit(f"State file not found: {path}")
            raise SystemExit(f"State file did not change before timeout: {path}")
        time.sleep(0.05)


def compact_coord(unit: dict[str, Any]) -> str:
    bits = [f"({unit.get('x')},{unit.get('y')})"]
    if unit.get("dir") is not None:
        bits.append(f"dir={unit.get('dir')}")
    if unit.get("id") is not None:
        bits.append(f"id={unit.get('id')}")
    return " ".join(bits)


def print_group(title: str, units: list[dict[str, Any]], *, limit: int) -> None:
    print(title + ":")
    if not units:
        print("  <none>")
        return

    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for unit in units:
        grouped[str(unit.get("name") or "<unknown>")].append(unit)

    printed = 0
    for name in sorted(grouped):
        coords = ", ".join(compact_coord(unit) for unit in grouped[name])
        print(f"  {name}: {coords}")
        printed += 1
        if limit and printed >= limit:
            remaining = len(grouped) - printed
            if remaining > 0:
                print(f"  ... {remaining} more groups")
            return


def summarize(state: dict[str, Any], path: Path, *, limit: int) -> None:
    meta = state.get("meta", {})
    units = state.get("units", [])
    rules = state.get("rules", [])
    text_units = [unit for unit in units if unit.get("unit_type") == "text"]
    object_units = [unit for unit in units if unit.get("unit_type") != "text"]

    print(f"state_path={path}")
    print(
        "event="
        f"{meta.get('source')} turn={meta.get('turn')} seq={meta.get('sequence')} "
        f"last_command={meta.get('last_command')}"
    )
    print(
        "level="
        f"{meta.get('world')}/{meta.get('level')} "
        f"name={meta.get('level_name') or '<unknown>'} "
        f"size={meta.get('room_width')}x{meta.get('room_height')}"
    )
    print(f"counts=units:{len(units)} text:{len(text_units)} rules:{len(rules)}")

    print()
    print("Rules:")
    if not rules:
        print("  <none>")
    else:
        for rule in rules[: limit or None]:
            label = rule.get("text")
            flags = []
            if rule.get("base"):
                flags.append("base")
            if rule.get("visible"):
                flags.append("visible")
            suffix = f" [{' '.join(flags)}]" if flags else ""
            print(f"  {label}{suffix}")
        if limit and len(rules) > limit:
            print(f"  ... {len(rules) - limit} more rules")

    print()
    print_group("Objects", object_units, limit=limit)
    print()
    print_group("Text", text_units, limit=limit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--path", type=Path, help="Override state JSON path")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    parser.add_argument("--wait", action="store_true", help="Wait until the state file exists or changes")
    parser.add_argument("--timeout", type=float, default=3.0, help="Seconds to wait with --wait")
    parser.add_argument(
        "--since-mtime",
        type=float,
        help="With --wait, require the file mtime to become greater than this value",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit printed rule/object groups")
    args = parser.parse_args()

    path = state_path_from_args(args)
    state = load_state(path, wait=args.wait, timeout=args.timeout, since_mtime=args.since_mtime)
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        summarize(state, path, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
