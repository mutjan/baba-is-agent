#!/usr/bin/env python3
"""Full first-run benchmark starter for new Baba Is You agents.

This script is an onboarding wrapper around the existing tools. It does not
solve levels and does not replace baba_benchmark.py; it checks local readiness,
prints the rules that new agents usually miss, starts the benchmark timer, and
prints the next commands/tools to use.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from baba_config import load_config, update_config_value


RULES_PRIMER = """\
Basic Baba Is You rules for benchmark agents

- Rules are made from visible text, usually NOUN IS PROPERTY.
- YOU marks the controllable object. WIN marks what wins the level.
- STOP blocks movement. DEFEAT destroys YOU when touched.
- SHUT and OPEN remove each other when they collide, such as a key opening a door.
- Text objects are pushable by default. TEXT IS PUSH is a base rule, so it may
  be active even when the level does not show those words explicitly.
- PUSH means a YOU object can push that object or text one tile if the whole
  pushed chain has free space behind it. If the space behind the chain is STOP,
  the map edge, or another unpushable blocker, the push does not happen.
- Pushed text can create or break rules. Moving IS, YOU, WIN, STOP, PUSH, OPEN,
  SHUT, or noun words is often the main way to solve a level.
- On the world map/overworld, do not look for Baba. The controllable object is
  the live-state cursor under the base rule cursor is select; use map_route or
  navigate_next to enter a real level.
- Passing evidence is the save completion status becoming 3, not a command exit
  code and not frontmost=Chowdren.
"""


def run_display(command: list[str], *, check: bool) -> int:
    print()
    print("$ " + " ".join(command))
    sys.stdout.flush()
    proc = subprocess.run(command, cwd=ROOT, check=False)
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc.returncode


def print_section(title: str) -> None:
    print()
    print("== " + title + " ==")


def ensure_ready(args: argparse.Namespace) -> tuple[object, str]:
    config = load_config(args.config)
    if args.run_id and not args.dry_run:
        update_config_value(config.config_path, "current_run_id", args.run_id)
        config = load_config(config.config_path)
    run_id = args.run_id or config.current_run_id

    print_section("Local config")
    print(f"config_path={config.config_path}")
    print(f"game_files_found={config.game_files_found}")
    print(f"state_exporter_installed={config.state_exporter_installed}")
    print(f"current_run_id={config.current_run_id or '<unset>'}")
    if args.run_id:
        print(f"effective_run_id={run_id}")
    print(f"input_delay={config.input_delay}")

    if not config.game_files_found:
        raise SystemExit(
            "Game files were not found. Review game_root in baba_config.json, "
            "then rerun this script."
        )
    if not config.state_exporter_installed:
        raise SystemExit(
            "The live state exporter is not installed. Run "
            "`python3 scripts/install_baba_state_exporter.py`, restart Baba Is You, "
            "then rerun this script."
        )
    if not run_id:
        raise SystemExit(
            "current_run_id is unset. Rerun with "
            "`python3 start_benchmark.py --run-id 001_agent_model` "
            "or set it with `python3 scripts/baba_config.py --set-current-run-id 001_agent_model`."
        )
    return config, run_id


def benchmark_command(args: argparse.Namespace, run_id: str) -> list[str]:
    command = [sys.executable, str(SCRIPTS_DIR / "baba_benchmark.py")]
    if args.config:
        command.extend(["--config", str(args.config)])
    if args.save_dir:
        command.extend(["--save-dir", str(args.save_dir)])
    command.extend(["--run-id", run_id])
    if args.force_new:
        command.append("--force-new")
    if args.enter_next:
        command.append("--enter-next")
    if args.dry_run:
        command.append("--dry-run")
    if args.after_restart_wait is not None:
        command.extend(["--after-restart-wait", str(args.after_restart_wait)])
    return command


def inspect_commands(args: argparse.Namespace) -> list[list[str]]:
    state = [sys.executable, str(SCRIPTS_DIR / "read_baba_state.py"), "--limit", str(args.state_limit)]
    rules = [sys.executable, str(SCRIPTS_DIR / "parse_baba_level.py"), "--rules-only"]
    if args.config:
        state.extend(["--config", str(args.config)])
        rules.extend(["--config", str(args.config)])
    if args.save_dir:
        state.extend(["--save-dir", str(args.save_dir)])
        rules.extend(["--save-dir", str(args.save_dir)])
    return [state, rules]


def print_next_steps() -> None:
    print_section("Next agent loop")
    print("Prefer MCP tools when available:")
    print("1. inspect_state")
    print("2. try_moves with the shortest meaningful move segment")
    print("3. restart_level if an experiment goes bad")
    print("4. navigate_next when on the world map/overworld")
    print("5. record_pass only after completion status is 3")
    print()
    print("Script fallback:")
    print("python3 scripts/baba_try.py '<short move segment>'")
    print("python3 scripts/baba_benchmark.py --record-pass --moves '<verified full route>' --note '<short summary>'")
    print()
    print("For the full agent operating contract, read AGENTS.md.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--run-id", help="Set/use runs/<run_id>, e.g. 002_claude_sonnet")
    parser.add_argument("--force-new", action="store_true", help="Start a new attempt even if one is active")
    parser.add_argument("--enter-next", action="store_true", help="Enter the next map level before starting")
    parser.add_argument("--dry-run", action="store_true", help="Print benchmark action without writing timer files")
    parser.add_argument("--skip-primer", action="store_true", help="Do not print the Baba rules primer")
    parser.add_argument("--no-inspect", action="store_true", help="Do not print current state and rules after starting")
    parser.add_argument("--state-limit", type=int, default=12, help="Limit read_baba_state groups during inspection")
    parser.add_argument("--after-restart-wait", type=float, help="Wait passed to baba_benchmark.py")
    args = parser.parse_args()

    print_section("Baba benchmark starter")
    print("This entry is for a freshly cloned repo or a newly assigned agent.")
    print("It keeps scripts as the source of truth and prefers MCP as the agent interface.")

    if not args.skip_primer:
        print_section("Rules primer")
        print(RULES_PRIMER.rstrip())

    _config, run_id = ensure_ready(args)

    print_section("Start benchmark timer")
    code = run_display(benchmark_command(args, run_id), check=False)
    if code != 0:
        return code

    if not args.no_inspect:
        print_section("Current state and initial rules")
        for command in inspect_commands(args):
            code = run_display(command, check=False)
            if code != 0:
                return code

    print_next_steps()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
