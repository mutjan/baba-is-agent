#!/usr/bin/env python3
"""Benchmark Baba Is You level attempts and maintain local run notes.

Default behavior:

- Create a local attempt handoff under runs/<run_id>/.
- Record the current state immediately so the run measures learning and solving
  from the current state, not replay of known routes.
- Record a pass later with --record-pass after the agent solves the level.
  The primary score is pass step count, not wall-clock time.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from baba_config import load_config, update_config_value
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
RUN_FILE_NAMES = {
    "benchmark_log": "baba_benchmark_log.md",
    "level_notes": "baba_level_notes.md",
    "learned_rules": "baba_learned_rules.md",
    "growth_diary": "baba_growth_diary.md",
}
KNOWN_ROUTES_NAME = "baba_known_routes.json"
RUN_TEMPLATES = {
    "level_notes": RUNS_ROOT / "baba_level_notes.template.md",
    "learned_rules": RUNS_ROOT / "baba_learned_rules.template.md",
    "growth_diary": RUNS_ROOT / "baba_growth_diary.template.md",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_dir_for(run_id: str) -> Path:
    if not re.fullmatch(r"\d{3}_[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise SystemExit("run_id must look like 001_codex_gpt55 or 002_claude_sonnet")
    return RUNS_ROOT / run_id


def resolve_run_id(args: argparse.Namespace, config: Any) -> str:
    explicit = args.run_id or os.environ.get("BABA_RUN_ID")
    run_id = explicit or config.current_run_id
    if not run_id:
        raise SystemExit(
            "No current_run_id configured. Run "
            "`python3 scripts/baba_config.py --set-current-run-id 001_agent_model` "
            "or pass --run-id."
        )
    run_dir_for(run_id)
    if explicit and explicit != config.current_run_id and not args.dry_run:
        update_config_value(config.config_path, "current_run_id", explicit)
    return run_id


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


def any_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def save_file_for(save_dir: Path) -> Path:
    return current_save_file(save_dir)


def completion_status(save_dir: Path, world: str, level: str) -> int | None:
    save = read_ini_like(save_file_for(save_dir))
    return parse_int(save.get(world, {}).get(level))


def live_state_meta(save_dir: Path) -> dict[str, Any]:
    state = load_save_state(save_file_for(save_dir))
    if not state:
        return {}
    meta = state.get("meta") or {}
    return meta if isinstance(meta, dict) else {}


def live_turn_count(save_dir: Path, world: str, level: str) -> int | None:
    meta = live_state_meta(save_dir)
    if meta.get("world") != world or meta.get("level") != level:
        return None
    turn = meta.get("turn")
    return turn if isinstance(turn, int) else None


def live_pass_turn_count(save_dir: Path, world: str, level: str) -> int | None:
    meta = live_state_meta(save_dir)
    if meta.get("world") != world or meta.get("level") != level:
        return None
    if meta.get("source") != "level_win_after" and meta.get("last_command") != "win":
        return None
    turn = meta.get("turn")
    return turn if isinstance(turn, int) else None


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


def static_level_name(config: Any, world: str, level: str) -> str:
    ld_path = config.game_root / world / f"{level}.ld"
    if not ld_path.exists():
        return level
    return read_ini_like(ld_path).get("general", {}).get("name") or level


def expand_moves(raw: str) -> list[str]:
    moves: list[str] = []
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        if "*" in token:
            name, count = token.split("*", 1)
            moves.extend([name] * int(count))
        else:
            moves.append(token)
    return moves


def ensure_run_files(run_dir: Path, files: dict[str, Path]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    defaults = {
        "benchmark_log": "# Baba Benchmark Log\n\n",
        "level_notes": "# Baba Is You Level Notes\n\n",
        "learned_rules": "# Baba Is You Learned Rules\n\n",
        "growth_diary": "# Baba Growth Diary\n\n",
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


def known_routes_path(run_dir: Path) -> Path:
    return run_dir / KNOWN_ROUTES_NAME


def load_known_routes(path: Path) -> dict[str, Any]:
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("schema") == "codex-baba-known-routes-v1" and isinstance(doc.get("routes"), dict):
            return doc
    return {"schema": "codex-baba-known-routes-v1", "routes": {}}


def update_known_routes(record: dict[str, Any], run_dir: Path) -> None:
    path = known_routes_path(run_dir)
    doc = load_known_routes(path)
    routes = doc["routes"]
    route = routes.setdefault(record["level"], {})

    previous_best = any_int(route.get("best_score_steps"))
    score_steps = record["score_steps"]
    is_best = previous_best is None or score_steps < previous_best

    route.update(
        {
            "name": record["name"],
            "moves": record["moves"],
            "hold_ms": record["hold_ms"],
            "note": record.get("note") or route.get("note", ""),
            "last_score_steps": score_steps,
            "last_score_source": record["score_source"],
            "last_game_turns": record.get("game_turns"),
            "last_route_steps": record["route_steps"],
            "last_elapsed_seconds": record["elapsed_seconds"],
            "last_completed_at": record["completed_at"],
            "attempts": int(route.get("attempts") or 0) + 1,
        }
    )
    if is_best:
        route.update(
            {
                "best_score_steps": score_steps,
                "best_score_source": record["score_source"],
                "best_game_turns": record.get("game_turns"),
                "best_route_steps": record["route_steps"],
                "best_elapsed_seconds": record["elapsed_seconds"],
                "best_completed_at": record["completed_at"],
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def update_run_files(record: dict[str, Any], run_dir: Path, files: dict[str, Path]) -> None:
    ensure_run_files(run_dir, files)
    update_known_routes(record, run_dir)
    level = record["level"]
    name = record["name"]
    timestamp = record["completed_at"]
    elapsed = record["elapsed_seconds"]
    moves = record["moves"]
    route_steps = record["route_steps"]
    score_steps = record["score_steps"]
    score_source = record["score_source"]
    game_turns = record.get("game_turns")
    evidence = record["evidence"]
    note = record.get("note") or ""

    append(
        files["benchmark_log"],
        (
            f"## {timestamp} {level} / {name}\n\n"
            f"- result: pass\n"
            f"- score_steps: {score_steps}\n"
            f"- score_source: {score_source}\n"
            f"- game_turns: {game_turns}\n"
            f"- route_steps: {route_steps}\n"
            f"- elapsed_seconds: {elapsed}\n"
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
            f"结果：`{evidence}`，评分步数 `{score_steps}`"
            f"（来源：`{score_source}`），路线展开 `{route_steps}` 步；"
            f"墙钟用时 `{elapsed}` 秒仅作参考。\n\n"
        ),
    )
    append(
        files["learned_rules"],
        (
            f"\n## Benchmark Evidence: {level} / {timestamp}\n\n"
            f"- `{level}` 独立 benchmark 通过，证据为 `{evidence}`，评分步数 `{score_steps}`"
            f"（来源：`{score_source}`）。\n"
            f"- 若本关产生了通用经验，接手 agent 应把它改写到上方对应主题；无通用经验时保留这条机械记录即可。\n\n"
        ),
    )
    append(
        files["growth_diary"],
        (
            f"\n## {timestamp} {level} / {name}\n\n"
            f"我这一关学到的是：{note or '先写这关真正改变我理解的一点。'}\n\n"
            f"我一开始看到的局面是：\n\n"
            f"真正改变我理解的是：\n\n"
            f"下次遇到类似关卡，我会先：\n\n"
            f"通关评分步数 `{score_steps}`，路线展开 `{route_steps}` 步。\n\n"
        ),
    )


def start_attempt_record(
    config: Any,
    save_dir: Path,
    world: str,
    level: str,
    name: str | None,
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
        "name": name or level,
        "initial_status": completion_status(save_dir, world, level),
        "initial_turn": live_turn_count(save_dir, world, level),
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
            f"- turn_at_start: `{record['initial_turn']}`\n"
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
    run_dir: Path,
    files: dict[str, Path],
    active_path: Path,
) -> None:
    if not active_path.exists():
        raise SystemExit(f"No active benchmark attempt found: {active_path}")
    active = json.loads(active_path.read_text(encoding="utf-8"))

    slot, current_world, _current = current_level(save_dir)
    level = args.level or active.get("level")
    world = args.world or active.get("world") or current_world
    if not level or not world:
        raise SystemExit(f"Active benchmark attempt is missing world/level: {active_path}")
    status = completion_status(save_dir, world, level)
    if status != 3 and not args.allow_without_status:
        raise SystemExit(f"{level} is not complete yet: status={status}")
    if not args.moves:
        raise SystemExit("--record-pass requires --moves")

    started_at = float(active.get("start_time") or time.time())
    elapsed = max(0.0, time.time() - started_at)
    completed_at = iso(utc_now())
    rounded_elapsed = round(elapsed, 3)
    route_steps = len(expand_moves(args.moves))
    game_turns = live_pass_turn_count(save_dir, world, level)
    score_steps = game_turns if game_turns is not None else route_steps
    score_source = "live_state_turn" if game_turns is not None else "expanded_route_steps"
    record = {
        "level": level,
        "name": args.name or active.get("name") or level,
        "moves": args.moves,
        "expanded_steps": route_steps,
        "route_steps": route_steps,
        "game_turns": game_turns,
        "score_steps": score_steps,
        "score_source": score_source,
        "hold_ms": int(args.hold_ms or 90),
        "elapsed_seconds": rounded_elapsed,
        "completed_at": completed_at,
        "evidence": f"completion_status={level}={status}",
        "note": args.note,
        "slot": slot,
        "world": world,
        "current_world": current_world,
    }
    if not args.no_run_updates:
        update_run_files(record, run_dir, files)
    if active_path.exists():
        active_path.unlink()
    print(
        f"recorded_pass level={level} "
        f"score_steps={record['score_steps']} score_source={record['score_source']} "
        f"route_steps={record['route_steps']} game_turns={record['game_turns']} "
        f"elapsed_seconds={record['elapsed_seconds']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--world", help="World override for --record-pass")
    parser.add_argument("--level", help="Level id. Defaults to current save Previous.")
    parser.add_argument("--name", help="Level name for a newly recorded manual route")
    parser.add_argument("--moves", help="Route moves for --record-pass")
    parser.add_argument("--note", default="", help="Short route note for --record-pass")
    parser.add_argument("--hold-ms", type=int, help="Override route/default key hold")
    parser.add_argument("--after-restart-wait", type=float, default=0.5)
    parser.add_argument("--enter-next", action="store_true", help="Enter the next unlocked map level before benchmarking")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned action without sending keys or writing files")
    parser.add_argument("--record-pass", action="store_true", help="Record an interactively solved level using the active attempt")
    parser.add_argument("--allow-without-status", action="store_true", help="Allow --record-pass even if save status is not 3")
    parser.add_argument("--no-run-updates", action="store_true", help="Do not append local runs/<run_id>/*.md records")
    parser.add_argument("--force-new", action="store_true", help="Start a new attempt even if one is already active")
    parser.add_argument(
        "--run-id",
        help="Per-agent run directory name, e.g. 001_codex_gpt55. Overrides config current_run_id.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    run_id = resolve_run_id(args, config)
    run_dir = run_dir_for(run_id)
    files = run_files(run_dir)
    active_path = active_attempt_path(run_dir)

    if args.record_pass:
        record_manual_pass(args, config, save_dir, run_dir, files, active_path)
        return 0

    if args.enter_next:
        command = [sys.executable, str(SCRIPTS_DIR / "baba_map_route.py"), "--execute"]
        if args.dry_run:
            print("enter_next_command=" + " ".join(command))
        else:
            subprocess.run(command, check=True)
            time.sleep(args.after_restart_wait)

    slot, world, level = current_level(save_dir) if not args.level else (*current_level(save_dir)[:2], args.level)
    name = args.name or static_level_name(config, world, level)

    if active_path.exists() and not args.force_new:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        elapsed = max(0.0, time.time() - float(active.get("start_time") or time.time()))
        print(f"active_attempt={active_path}")
        print(f"run_id={run_id}")
        print(f"level={active.get('world')}/{active.get('level')} name={active.get('name')}")
        print(f"elapsed_seconds={round(elapsed, 3)}")
        print("score_metric=pass_step_count")
        print("next_commands=python3 scripts/read_baba_state.py ; python3 scripts/parse_baba_level.py --rules-only ; python3 scripts/baba_try.py '<short segment>'")
        print(f"record_command=python3 scripts/baba_benchmark.py --record-pass --moves '<verified full route>' --note '<short summary>'")
        return 0

    if not args.dry_run:
        start_attempt_record(config, save_dir, world, level, name, run_dir, files, active_path)
    print(f"started_attempt slot={slot} world={world} level={level} name={name} run_id={run_id}")
    print(f"active={active_path}")
    print("benchmark_mode=from_zero_state_guided")
    print("score_metric=pass_step_count")
    print("known_routes_used=0")
    print("next_commands=python3 scripts/read_baba_state.py ; python3 scripts/parse_baba_level.py --rules-only ; python3 scripts/baba_try.py '<short segment>'")
    print(f"record_command=python3 scripts/baba_benchmark.py --record-pass --moves '<verified full route>' --note '<short summary>'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
