#!/usr/bin/env python3
"""Benchmark Baba Is You level attempts and maintain local run notes.

Default behavior:

- If the current level has a known route, optionally restart, execute the route,
  time from first sent key until completion evidence is observed, then update
  the route JSON and local runs files.
- If the current level has no known route, create a local attempt handoff under
  runs/<run_id>/ so the next agent starts with the state-guided loop instead of
  guessing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from baba_config import load_config
from baba_play_known_route import (
    DEFAULT_ROUTES_PATH,
    expand_moves,
    known_route_command,
    known_route_display_command,
    load_routes,
    route_delay,
    route_hold_ms,
    route_map,
    save_routes,
)
from parse_baba_level import (
    active_rules,
    current_level,
    parse_currobjlist,
    parse_global_tiles,
    parse_level_binary,
    read_ini_like,
)
from read_baba_state import current_save_file, load_save_state


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
RUNS_ROOT = ROOT / "runs"
DEFAULT_RUN_ID = "001_codex_gpt55"
RUN_FILE_NAMES = {
    "benchmark_log": "baba_benchmark_log.md",
    "level_notes": "baba_level_notes.md",
    "learned_rules": "baba_learned_rules.md",
    "growth_diary": "baba_growth_diary_xiaohongshu.md",
}
RUN_TEMPLATES = {
    "level_notes": RUNS_ROOT / "baba_level_notes.template.md",
    "learned_rules": RUNS_ROOT / "baba_learned_rules.template.md",
    "growth_diary": RUNS_ROOT / "baba_growth_diary_xiaohongshu.template.md",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_dir_for(run_id: str) -> Path:
    if not re.fullmatch(r"\d{3}_[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise SystemExit("run_id must look like 001_codex_gpt55 or 002_claude_sonnet")
    return RUNS_ROOT / run_id


def active_attempt_path(run_dir: Path) -> Path:
    return run_dir / "baba_benchmark_active.json"


def run_files(run_dir: Path) -> dict[str, Path]:
    return {key: run_dir / name for key, name in RUN_FILE_NAMES.items()}


def parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def save_file_for(save_dir: Path) -> Path:
    return current_save_file(save_dir)


def completion_status(save_dir: Path, world: str, level: str) -> int | None:
    save = read_ini_like(save_file_for(save_dir))
    return parse_int(save.get(world, {}).get(level))


def state_win_event(save_file: Path, level: str, start_mtime: float | None) -> bool:
    if not save_file.exists():
        return False
    if start_mtime is not None and save_file.stat().st_mtime <= start_mtime:
        return False
    state = load_save_state(save_file)
    if state is None:
        return False
    meta = state.get("meta", {})
    if meta.get("level") != level:
        return False
    return "level_win_after" in {meta.get("source"), meta.get("last_command")}


def completion_evidence(
    save_dir: Path,
    world: str,
    level: str,
    *,
    initial_status: int | None,
    start_mtime: float | None,
) -> str | None:
    save_file = save_file_for(save_dir)
    status = completion_status(save_dir, world, level)
    changed = save_file.exists() and (start_mtime is None or save_file.stat().st_mtime > start_mtime)
    if status == 3 and initial_status != 3:
        return f"completion_status={level}=3"
    if status == 3 and state_win_event(save_file, level, start_mtime):
        return f"level_win_after and completion_status={level}=3"
    if status == 3 and changed:
        try:
            _slot, _world, current = current_level(save_dir)
        except Exception:
            current = level
        if current != level:
            return f"left_level={current} and completion_status={level}=3"
    return None


def initial_rules(config: Any, world: str, level: str) -> list[str]:
    level_dir = config.game_root / world
    ld_path = level_dir / f"{level}.ld"
    l_path = level_dir / f"{level}.l"
    if not ld_path.exists() or not l_path.exists():
        return []
    level_data = ld_path.read_text(errors="replace")
    code_to_name, _name_to_symbol = parse_global_tiles(config.game_root.parent / "values.lua")
    level_code_to_name, _level_name_to_symbol = parse_currobjlist(level_data)
    code_to_name.update(level_code_to_name)
    width, height, layers = parse_level_binary(l_path)
    return [f"{first} {middle} {last}" for _direction, _coord, first, middle, last in active_rules(width, height, layers, code_to_name)]


def run_command_with_completion_watch(
    command: list[str],
    *,
    save_dir: Path,
    world: str,
    level: str,
    initial_status: int | None,
    completion_timeout: float,
) -> tuple[float, str]:
    save_file = save_file_for(save_dir)
    start_mtime = save_file.stat().st_mtime if save_file.exists() else None
    start = time.monotonic()
    proc = subprocess.Popen(command)
    evidence: str | None = None
    evidence_time: float | None = None
    terminated_after_evidence = False

    while True:
        evidence = completion_evidence(
            save_dir,
            world,
            level,
            initial_status=initial_status,
            start_mtime=start_mtime,
        )
        if evidence is not None:
            evidence_time = time.monotonic()
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)

    return_code = proc.poll()
    if evidence_time is not None and return_code is None:
        proc.terminate()
        terminated_after_evidence = True
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    else:
        proc.wait()

    deadline = time.monotonic() + completion_timeout
    while evidence is None and time.monotonic() < deadline:
        evidence = completion_evidence(
            save_dir,
            world,
            level,
            initial_status=initial_status,
            start_mtime=start_mtime,
        )
        if evidence is not None:
            evidence_time = time.monotonic()
            break
        time.sleep(0.05)

    if evidence is None or evidence_time is None:
        raise SystemExit(f"Route finished but no pass evidence appeared for {level}")

    if proc.returncode not in (0, None) and not terminated_after_evidence:
        raise SystemExit(f"Route command exited {proc.returncode} after pass evidence: {evidence}")

    return evidence_time - start, evidence


def update_route_timing(
    routes_doc: dict[str, Any],
    level: str,
    *,
    elapsed: float,
    completed_at: str,
    moves: str | None = None,
    name: str | None = None,
    note: str | None = None,
    hold_ms: int | None = None,
) -> dict[str, Any]:
    routes = route_map(routes_doc)
    route = routes.setdefault(level, {})
    if name:
        route.setdefault("name", name)
    route.setdefault("name", level)
    if moves:
        route["moves"] = moves
    if note:
        route["note"] = note
    route.setdefault("note", "")
    if hold_ms is not None and hold_ms != 90:
        route["hold_ms"] = hold_ms
    rounded = round(elapsed, 3)
    route["last_elapsed_seconds"] = rounded
    best = route.get("best_elapsed_seconds")
    if best is None or rounded < float(best):
        route["best_elapsed_seconds"] = rounded
    route["last_completed_at"] = completed_at
    route["attempts"] = int(route.get("attempts") or 0) + 1
    return route


def ensure_run_files(run_dir: Path, files: dict[str, Path]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    defaults = {
        "benchmark_log": "# Baba Benchmark Log\n\n",
        "level_notes": "# Baba Is You Level Notes\n\n",
        "learned_rules": "# Baba Is You Learned Rules\n\n",
        "growth_diary": "# 我玩 Baba Is You 的成长日记  by GPT-5.5\n\n",
    }
    for key, path in files.items():
        if not path.exists():
            template = RUN_TEMPLATES.get(key)
            if template is not None and template.exists():
                path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                path.write_text(defaults[key], encoding="utf-8")


def append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def update_run_files(record: dict[str, Any], run_dir: Path, files: dict[str, Path]) -> None:
    ensure_run_files(run_dir, files)
    level = record["level"]
    name = record["name"]
    timestamp = record["completed_at"]
    elapsed = record["elapsed_seconds"]
    moves = record["moves"]
    steps = record["expanded_steps"]
    evidence = record["evidence"]
    note = record.get("note") or ""

    append(
        files["benchmark_log"],
        (
            f"## {timestamp} {level} / {name}\n\n"
            f"- result: pass\n"
            f"- elapsed_seconds: {elapsed}\n"
            f"- expanded_steps: {steps}\n"
            f"- evidence: `{evidence}`\n"
            f"- route: `{moves}`\n\n"
        ),
    )
    append(
        files["level_notes"],
        (
            f"\n## Benchmark Record: {level} / {name} / {timestamp}\n\n"
            f"已验证路线：\n\n"
            f"```bash\npython3 scripts/baba_send_keys.py '{moves}' --hold-ms {record['hold_ms']}\n```\n\n"
            f"结果：`{evidence}`，用时 `{elapsed}` 秒。\n\n"
        ),
    )
    append(
        files["learned_rules"],
        (
            f"\n## Benchmark Evidence: {level} / {timestamp}\n\n"
            f"- `{level}` 路线复放通过，证据为 `{evidence}`，用时 `{elapsed}` 秒。\n"
            f"- 若本关产生了通用经验，接手 agent 应把它改写到上方对应主题；无通用经验时保留这条机械记录即可。\n\n"
        ),
    )
    append(
        files["growth_diary"],
        (
            f"\n## 自动素材：{level} / {name}\n\n"
            f"这关本次通关用时 `{elapsed}` 秒，路线共 `{steps}` 步。\n\n"
            f"可写入成长日记的核心点：{note or '待补充本关的认知变化。'}\n\n"
        ),
    )


def start_attempt_record(
    config: Any,
    save_dir: Path,
    world: str,
    level: str,
    route: dict[str, Any] | None,
    run_dir: Path,
    files: dict[str, Path],
    active_path: Path,
) -> dict[str, Any]:
    started_at = iso(utc_now())
    rules = initial_rules(config, world, level)
    record = {
        "schema": "codex-baba-benchmark-active-v1",
        "started_at": started_at,
        "start_time": time.time(),
        "world": world,
        "level": level,
        "name": (route or {}).get("name", level),
        "initial_status": completion_status(save_dir, world, level),
        "initial_rules": rules,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    active_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ensure_run_files(run_dir, files)
    append(
        files["benchmark_log"],
        (
            f"## {started_at} started {level} / {record['name']}\n\n"
            f"- status_at_start: `{record['initial_status']}`\n"
            f"- initial_rules: {', '.join(f'`{rule}`' for rule in rules) if rules else '`<unavailable>`'}\n"
            f"- next: solve with `scripts/baba_try.py`, then run "
            f"`python3 scripts/baba_benchmark.py --record-pass --moves '<route>' --note '<summary>'`.\n\n"
        ),
    )
    return record


def record_manual_pass(
    args: argparse.Namespace,
    config: Any,
    save_dir: Path,
    routes_doc: dict[str, Any],
    run_dir: Path,
    files: dict[str, Path],
    active_path: Path,
) -> None:
    if active_path.exists():
        active = json.loads(active_path.read_text(encoding="utf-8"))
    else:
        active = {}

    slot, world, current = current_level(save_dir)
    level = args.level or active.get("level") or current
    world = args.world or active.get("world") or world
    status = completion_status(save_dir, world, level)
    if status != 3 and not args.allow_without_status:
        raise SystemExit(f"{level} is not complete yet: status={status}")
    if not args.moves:
        raise SystemExit("--record-pass requires --moves")

    started_at = float(active.get("start_time") or time.time())
    elapsed = max(0.0, time.time() - started_at)
    completed_at = iso(utc_now())
    route = update_route_timing(
        routes_doc,
        level,
        elapsed=elapsed,
        completed_at=completed_at,
        moves=args.moves,
        name=args.name or active.get("name"),
        note=args.note,
        hold_ms=args.hold_ms,
    )
    save_routes(routes_doc, args.routes)
    record = {
        "level": level,
        "name": route.get("name", level),
        "moves": args.moves,
        "expanded_steps": len(expand_moves(args.moves)),
        "hold_ms": int(route.get("hold_ms", args.hold_ms or 90)),
        "elapsed_seconds": route["last_elapsed_seconds"],
        "completed_at": completed_at,
        "evidence": f"completion_status={level}={status}",
        "note": route.get("note", ""),
        "slot": slot,
        "world": world,
    }
    if not args.no_run_updates:
        update_run_files(record, run_dir, files)
    if active_path.exists():
        active_path.unlink()
    print(f"recorded_pass level={level} elapsed_seconds={record['elapsed_seconds']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTES_PATH, help="Known routes JSON path")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--world", help="World override for --record-pass")
    parser.add_argument("--level", help="Level id. Defaults to current save Previous.")
    parser.add_argument("--name", help="Level name for a newly recorded manual route")
    parser.add_argument("--moves", help="Route moves for --record-pass")
    parser.add_argument("--note", default="", help="Short route note for --record-pass")
    parser.add_argument("--hold-ms", type=int, help="Override route/default key hold")
    parser.add_argument("--delay", type=float, help="Override configured input_delay")
    parser.add_argument("--completion-timeout", type=float, default=5.0)
    parser.add_argument("--after-restart-wait", type=float, default=0.5)
    parser.add_argument("--enter-next", action="store_true", help="Enter the next unlocked map level before benchmarking")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart the level before executing a known route")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned action without sending keys or writing files")
    parser.add_argument("--record-pass", action="store_true", help="Record an interactively solved level using the active attempt timer")
    parser.add_argument("--allow-without-status", action="store_true", help="Allow --record-pass even if save status is not 3")
    parser.add_argument("--no-run-updates", action="store_true", help="Do not append local runs/<run_id>/*.md records")
    parser.add_argument(
        "--run-id",
        default=os.environ.get("BABA_RUN_ID", DEFAULT_RUN_ID),
        help="Per-agent run directory name, e.g. 001_codex_gpt55.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    routes_doc = load_routes(args.routes)
    routes = route_map(routes_doc)
    run_dir = run_dir_for(args.run_id)
    files = run_files(run_dir)
    active_path = active_attempt_path(run_dir)

    if args.record_pass:
        record_manual_pass(args, config, save_dir, routes_doc, run_dir, files, active_path)
        return 0

    if args.enter_next:
        command = [sys.executable, str(SCRIPTS_DIR / "baba_map_route.py"), "--execute"]
        if args.dry_run:
            print("enter_next_command=" + " ".join(command))
        else:
            subprocess.run(command, check=True)
            time.sleep(args.after_restart_wait)

    slot, world, level = current_level(save_dir) if not args.level else (*current_level(save_dir)[:2], args.level)
    route = routes.get(level)

    if route is None:
        if not args.dry_run:
            start_attempt_record(config, save_dir, world, level, None, run_dir, files, active_path)
        print(f"started_attempt slot={slot} world={world} level={level} active={active_path}")
        print("no_known_route=1")
        print("next_commands=python3 scripts/read_baba_state.py ; python3 scripts/parse_baba_level.py --rules-only ; python3 scripts/baba_try.py '<short segment>'")
        print(f"record_command=python3 scripts/baba_benchmark.py --run-id {args.run_id} --record-pass --moves '<verified full route>' --note '<short summary>'")
        return 0

    delay = route_delay(config.input_delay, args.delay)
    hold_ms = route_hold_ms(route, args.hold_ms)
    moves = str(route["moves"])
    expanded_steps = len(expand_moves(moves))
    print(f"benchmark_level={level} name={route['name']} steps={expanded_steps} delay={delay} hold_ms={hold_ms}")

    if args.dry_run:
        display = known_route_display_command(moves, delay=delay, hold_ms=hold_ms)
        print("route_command=" + shlex.join(display))
        print("would_update_routes=1")
        print("would_update_run_files=" + str(not args.no_run_updates))
        return 0

    if not args.no_restart:
        subprocess.run([sys.executable, str(SCRIPTS_DIR / "baba_restart.py")], check=True)
        time.sleep(args.after_restart_wait)

    initial_status = completion_status(save_dir, world, level)
    elapsed, evidence = run_command_with_completion_watch(
        known_route_command(moves, delay=delay, hold_ms=hold_ms),
        save_dir=save_dir,
        world=world,
        level=level,
        initial_status=initial_status,
        completion_timeout=args.completion_timeout,
    )
    completed_at = iso(utc_now())
    route = update_route_timing(routes_doc, level, elapsed=elapsed, completed_at=completed_at)
    save_routes(routes_doc, args.routes)
    record = {
        "level": level,
        "name": route.get("name", level),
        "moves": moves,
        "expanded_steps": expanded_steps,
        "hold_ms": hold_ms,
        "elapsed_seconds": route["last_elapsed_seconds"],
        "completed_at": completed_at,
        "evidence": evidence,
        "note": route.get("note", ""),
        "slot": slot,
        "world": world,
    }
    if not args.no_run_updates:
        update_run_files(record, run_dir, files)
    print(f"passed level={level} elapsed_seconds={record['elapsed_seconds']} evidence={evidence}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
