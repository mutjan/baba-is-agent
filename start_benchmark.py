#!/usr/bin/env python3
"""Full first-run benchmark starter for new Baba Is You agents.

This script is an onboarding wrapper around the existing tools. It does not
solve levels and does not replace baba_benchmark.py; it checks local readiness,
prints the rules that new agents usually miss, starts the benchmark attempt, and
prints the next commands/tools to use.
"""

from __future__ import annotations

import argparse
import json
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
- Before any PUSH/TEXT move, explicitly check the chain tail: every pushed item
  moves one tile, and the cell after the far end must be free.
- Pushed text can create or break rules. Moving IS, YOU, WIN, STOP, PUSH, OPEN,
  SHUT, or noun words is often the main way to solve a level.
- Dead corners and one-tile pockets are a general risk. If a key text/object is
  pushed against the edge, STOP, DEFEAT, or a position reachable from only one
  side, it may become unusable from the needed direction later. Treat this as a
  generic mechanism to test, not as a level-specific coordinate hint.
- On the world map/overworld, do not look for Baba. The controllable object is
  the live-state cursor under the base rule cursor is select; use MCP
  navigate_next or script fallback `python3 scripts/baba_map_route.py --execute`
  to enter a real level.
- On macOS, the app is configured as Baba Is You, but the live process may be
  Chowdren. Use app_status rather than checking only for a Baba Is You process.
- Passing evidence is the save completion status becoming 3, not a command exit
  code and not frontmost=Chowdren.
- MCP navigate_next / script baba_map_route.py --execute only enters a level. After entering, call
  start_benchmark before solving so the active attempt matches the live level.
- MCP tool names are not script names. There is no scripts/baba_navigate_next.py.
  If MCP is unavailable, use scripts/baba_map_route.py --execute.
- If start_benchmark reports active_state_mismatch=true, stop solving and run
  the printed --force-new command. Do not repair records with --record-pass
  --level unless the user explicitly asks for benchmark log repair.

Efficiency protocol

- First principles means shortest verifiable feedback loop, not exhaustive
  proof. Do not mentally simulate a whole solution before acting.
- Each solving loop should be: observe 1-3 facts, state one hypothesis with one
  expected observable delta, run one short check_moves/action_check segment, read
  the result, then continue/shorten/restart.
- Pick exactly one observable target per loop: change one rule, move one key
  text/object, approach one area, or verify one blocker.
- User-facing solving updates should be at most 5 lines: Observation,
  Hypothesis, Action, Result, Next.
- Do not validate a route in hidden thinking. Use check_moves or
  scripts/baba_action_check.py with an explicit --expect-* argument.
- Bare --expect-moved is weak for multi-step moves or pushed text. Use
  --expect-moved-delta UNIT:DIR or --expect-position UNIT X,Y so the script can
  verify direction or endpoint instead of only "something moved".
- After baba_suggest_hypotheses.py or one baba_search_route.py --analyze output,
  immediately choose one 1-8 step check_moves/action_check segment with an
  explicit expected delta. Do not write more than 5 lines of rule-arrangement
  reasoning before the next action_check.
- If the next target is a text/rule push, shrink the next action_check to 1-3
  steps before simulating the full route in prose.
- action_check rejects contradictory rule expectations, and completion status 3
  checks require an active WIN rule unless this segment explicitly expects a
  new X IS WIN rule.
- Guard critical rules as invariants. For example, while building wall is win,
  pass --expect-rule-kept 'wall is you'; when a bad rule would trap you, use
  --forbid-rule-added or --forbid-rule-present.
- If check_moves/action_check returns check=fail, first run
  read_baba_state.py --limit 60. Do not treat expanded_move_count as a safe
  undo count: blocked/no-op inputs can make z*N erase earlier successful
  progress. If undo is necessary, use baba_undo.py --steps 1 and observe.
  Do not explain what should have happened, do not continue from mental
  coordinates, do not run another long segment, and do not use action_check for
  undo.
- Keep normal level action segments to 1-8 moves unless the state change is
  completely predictable.
- If you start writing "this is complicated" or keep reconsidering the same
  branch, stop thinking and run a smaller observable test.
- Do not enumerate every possible text alignment or map route. Use tool output
  as the authority, then test the cheapest meaningful action.
- If a plan contains more than one action segment, write it to the current run's
  baba_route_plan.md first. Keep only 1-3 pending segments, each with moves,
  expected delta, state anchor, and status. check_moves/action_check appends its
  own planned segment plus observed result automatically.
- baba_route_plan.md is a scratchpad, not a solution source.
"""


LEVEL0_EXAMPLE = """\
Level 0 compact interactive example

This is a style example, not a general route source. It shows how to keep
thinking short and let tools validate the route. Level 0 starts with Baba at
(13,11), a pushable rock at (17,11), and the flag at (21,11).

1. Read the state and rules:
   MCP: inspect_state
   Script: python3 scripts/read_baba_state.py --limit 20

2. First short hypothesis:
   Observation: BABA IS YOU, ROCK IS PUSH, FLAG IS WIN; rock blocks the corridor.
   Hypothesis: right*4 should push the middle rock and prove the corridor plan works.
   Action:
     MCP check_moves arguments:
       {"moves":"right*4","expect_moved_delta":["rock:+x"]}
     Script fallback:
       python3 scripts/baba_action_check.py 'right*4' --expect-moved-delta rock:+x
   Result: if check=pass, continue from the new live state; if check=fail, only
   reread live state or restart. Do not repair in thought.

3. Second short hypothesis:
   Observation: the same corridor is still aligned with the flag.
   Hypothesis: four more rights should put Baba on the flag.
   Action:
     MCP check_moves arguments:
       {"moves":"right*4","expect_completion":true}
     Script fallback:
       python3 scripts/baba_action_check.py 'right*4' --expect-completion
   Result: completion_status=0level=3 is the pass evidence.

4. Record only after the win:
   MCP: record_pass with moves "right*8" and a short note.
   Script fallback:
     python3 scripts/baba_benchmark.py --record-pass --moves 'right*8' --note 'push rock right to reach flag'
"""


MCP_INSTALL_GUIDE = """\
If your agent supports project-scoped MCP config, prefer installing this server
at the project level so every new agent in this repo sees the same tools.

Claude Code project scope:

  claude mcp add --scope project baba-is-you -- python3 scripts/baba_mcp_server.py
  claude mcp get baba-is-you
  claude mcp list

This writes or updates .mcp.json in the repo. Before committing .mcp.json, keep
it portable: use relative paths, and do not include secrets or user-specific
/Users/... paths. A portable shape is:

  {
    "mcpServers": {
      "baba-is-you": {
        "command": "python3",
        "args": ["scripts/baba_mcp_server.py"]
      }
    }
  }

For Codex CLI, install the MCP server per user:

  codex mcp add baba-is-you -- python3 "$(pwd)/scripts/baba_mcp_server.py"
  codex mcp list

After installation, restart the agent session and call app_status or
start_benchmark through MCP.
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


def next_action_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, str(SCRIPTS_DIR / "baba_next_action.py"), "--json"]
    if args.config:
        command.extend(["--config", str(args.config)])
    if args.save_dir:
        command.extend(["--save-dir", str(args.save_dir)])
    return command


def map_gate(args: argparse.Namespace) -> bool:
    if args.enter_next:
        return False
    proc = subprocess.run(
        next_action_command(args),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return False
    try:
        action = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False
    if action.get("context") != "map":
        return False

    print_section("Map detected")
    print(f"world={action.get('world')}")
    print(f"level={action.get('level')}")
    print(f"name={action.get('name')}")
    print("Do not start a level benchmark on a map/sub-map.")
    print(f"next_mcp_tool={action.get('next_mcp_tool')}")
    print(f"next_script={action.get('next_script')}")
    print(f"reason={action.get('reason')}")
    print("After entering a real level, run start_benchmark again.")
    return True


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
    print("1. app_status to confirm the process/status-file situation")
    print("2. suggest_next_action if you are unsure")
    print("3. inspect_state")
    print("4. check_moves with one explicit expected delta")
    print("5. try_moves only when debugging raw deltas")
    print("6. restart_level if an experiment goes bad")
    print("7. undo_moves to undo the last failed action segment")
    print("8. return_to_map when you need to leave a level or sub-map")
    print("9. navigate_next when on the world map/overworld (MCP tool only)")
    print("10. record_pass only after completion status is 3")
    print()
    print("Script fallback:")
    print("MCP tool names are not script names; do not invent scripts/baba_navigate_next.py.")
    print("On a map/overworld, use: python3 scripts/baba_map_route.py --execute")
    print("After check=fail, first use: python3 scripts/read_baba_state.py --limit 60")
    print("If undo is truly needed, use one observed step: python3 scripts/baba_undo.py --steps 1")
    print("python3 scripts/baba_action_check.py '<short move segment>' --expect-moved-delta '<unit-or-text>:<dir>'")
    print("python3 scripts/baba_action_check.py '<short move segment>' --expect-position '<unit-or-text>' X,Y")
    print("python3 scripts/baba_try.py '<short move segment>'")
    print("python3 scripts/baba_benchmark.py --record-pass --moves '<verified full route>' --note '<short summary>'")
    print()
    print("Efficiency rule: explain one hypothesis, execute one short observable segment, then let the script decide.")
    print("Hypothesis rule: after suggest_hypotheses or one --analyze, immediately run one 1-8 step action_check; no >5-line rule-arrangement reasoning.")
    print("Text rule: for text/rule pushes, the next action_check should be 1-3 steps before any longer route prose.")
    print("Invariant rule: use --expect-rule-kept for current YOU/WIN setup and --forbid-rule-added for bad rules like wall is stop.")
    print("Movement rule: multi-step/text movement needs --expect-moved-delta or --expect-position; bare --expect-moved is only for tiny debugging.")
    print("Push rule: chain pushes need free space after the far end; corner/edge/pocket pushes are high-risk until a short action_check proves them safe.")
    print("Failure rule: after check=fail, read state first; expanded_move_count is not a safe undo count; only single-step observed undo unless manually overridden.")
    print("Route plan rule: action_check appends planned short segments and observed results to runs/<current_run_id>/baba_route_plan.md.")
    print("Output rule: keep each solving update to Observation/Hypothesis/Action/Result/Next, 5 lines max.")
    print()
    print("For the full agent operating contract, read AGENTS.md.")


def print_level0_example() -> None:
    print_section("Level 0 example")
    print(LEVEL0_EXAMPLE.rstrip())


def print_mcp_install_guide() -> None:
    print_section("Project-level MCP setup")
    print(MCP_INSTALL_GUIDE.rstrip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--run-id", help="Set/use runs/<run_id>, e.g. 002_claude_sonnet")
    parser.add_argument("--force-new", action="store_true", help="Start a new attempt even if one is active")
    parser.add_argument("--enter-next", action="store_true", help="Enter the next map level before starting")
    parser.add_argument("--dry-run", action="store_true", help="Print benchmark action without writing attempt files")
    parser.add_argument("--skip-primer", action="store_true", help="Do not print the Baba rules primer")
    parser.add_argument("--skip-example", action="store_true", help="Do not print the level 0 interaction example")
    parser.add_argument("--skip-mcp-install", action="store_true", help="Do not print project-level MCP setup help")
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
    if not args.skip_mcp_install:
        print_mcp_install_guide()
    if not args.skip_example:
        print_level0_example()

    _config, run_id = ensure_ready(args)

    if map_gate(args):
        return 0

    print_section("Start benchmark attempt")
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
