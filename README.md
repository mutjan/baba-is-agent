# Baba Is You Agent Control

Local macOS tooling for reading and controlling Baba Is You from agent clients.

Only supports macOS. Tested on Codex, ClaudeCode, OpenCode, and Claude-Agent-SDK.

## Demo

[![Watch the Demo](https://img.youtube.com/vi/nju_P7gPk3U/0.jpg)](https://www.youtube.com/watch?v=nju_P7gPk3U)

## What This Installs

This project gives an agent two local capabilities:

- read Baba Is You save files, level files, and optional live runtime state;
- send macOS keyboard input to the running Baba Is You app.

The tools do not edit save files to win levels.

For the agent objective, operating method, benchmark rules, and game primer,
read `AGENTS.md` after installation.

## Requirements

- macOS.
- Steam version of Baba Is You installed locally.
- Python 3.
- Xcode Command Line Tools, for `clang`.
- macOS Accessibility permission for the app running these scripts, such as an
  agent app or Terminal.
- Baba Is You should be running before sending keys.

On macOS, the app/bundle name is usually `Baba Is You`, but the live process can
appear as the engine name `Chowdren`. Do not use `processes contains "Baba Is
You"` as the only running check; use `scripts/baba_app_status.py` or MCP
`app_status`.

The first key-send may also trigger macOS prompts for Automation or
Accessibility. Grant access to the process that runs the scripts.

## Installation

Clone the repo and enter it:

```bash
git clone https://github.com/mutjan/baba-is-agent.git
cd baba-is-agent
```

Create and inspect the local config:

```bash
python3 scripts/baba_config.py
```

On first run this creates `baba_config.json` and stops. Review `game_root` and
`save_dir`, then rerun the same command. The output should show:

```text
game_files_found=True
```

Install the live state exporter only if `state_exporter_installed=False`:

```bash
python3 scripts/install_baba_state_exporter.py
```

Restart Baba Is You after installing, then verify state reads:

```bash
python3 scripts/baba_app_status.py
python3 scripts/read_baba_state.py
python3 scripts/parse_baba_level.py --rules-only
```

If `state_exporter_installed=True`, skip the installer. That flag means the game
already has the agent Lua exporter in place.

## Configuration

The repo does not store machine-specific paths. First run creates local
`baba_config.json` from `baba_config.example.json`; the generated file is ignored
by git.

Default config:

```json
{
  "game_root": "~/Library/Application Support/Steam/steamapps/common/Baba Is You/Baba Is You.app/Contents/Resources/Data/Worlds",
  "save_dir": "~/Library/Application Support/Baba_Is_You",
  "app_name": "Baba Is You",
  "input_delay": 0.02,
  "game_files_found": false,
  "state_exporter_installed": false,
  "current_run_id": ""
}
```

Use `BABA_CONFIG=/path/to/config.json` or `--config /path/to/config.json` for a
different config file. Adjust `input_delay` if another machine needs a slower or
faster key interval.

The generated config refreshes `game_files_found` and
`state_exporter_installed` from the local filesystem. Treat
`state_exporter_installed=true` as the "game is already modded" flag and do not
rerun the exporter installer unless intentionally repairing it.

Set `current_run_id` to the current agent/model run folder, such as
`001_agent_model` or `002_claude_sonnet`:

```bash
python3 scripts/baba_config.py --set-current-run-id 001_agent_model
```

## MCP Server

MCP-capable agents should use the dependency-free stdio wrapper by default:

```bash
python3 scripts/baba_mcp_server.py
```

Example MCP config shape:

```json
{
  "mcpServers": {
    "baba-is-you": {
      "command": "python3",
      "args": ["scripts/baba_mcp_server.py"]
    }
  }
}
```

### Project-Level MCP Setup

If the agent supports project-scoped MCP configuration, install the server at
the project level so future agents entering this repo see the same tools.

Claude Code:

```bash
claude mcp add --scope project baba-is-you -- python3 scripts/baba_mcp_server.py
claude mcp get baba-is-you
claude mcp list
```

This writes or updates `.mcp.json` in the repo. Before committing that file,
make sure it uses relative paths like `scripts/baba_mcp_server.py` and contains
no secrets or user-specific `/Users/...` paths.

For Codex CLI, install the MCP server per user:

```bash
codex mcp add baba-is-you -- python3 "$(pwd)/scripts/baba_mcp_server.py"
codex mcp list
```

Restart the agent session after installation, then call MCP `app_status` or
`start_benchmark`.

List exposed tools:

```bash
python3 scripts/baba_mcp_server.py --list-tools
```

Current tools:

- `app_status`
- `config_status`
- `set_current_run_id`
- `start_benchmark`
- `inspect_state`
- `suggest_next_action`
- `read_state`
- `parse_rules`
- `try_moves`
- `check_moves`
- `restart_level`
- `undo_moves`
- `return_to_map`
- `navigate_next` (MCP tool only; script fallback is
  `python3 scripts/baba_map_route.py --execute`)
- `map_route`
- `play_known_route`
- `record_pass`

MCP tool names are not script names. Do not invent files from tool names; for
example, there is no `scripts/baba_navigate_next.py`.

## Agent Handoff

After installation and configuration, a new agent can start from the root entry:

```bash
python3 start_benchmark.py --run-id 001_agent_model
```

That script checks local readiness, prints the Baba rules primer, starts or
resumes the benchmark attempt through the core script, and points the agent to
the next MCP-first loop. The full target and operation contract lives in
`AGENTS.md`.

Use this dry run to verify the handoff without writing attempt files:

```bash
python3 start_benchmark.py --dry-run --skip-primer --no-inspect
```

## Tool Reference

- `start_benchmark.py`: root onboarding entry for a freshly cloned repo or newly
  assigned agent.
- `scripts/baba_config.py`: shared config loader, first-run config creation, and
  local game/exporter status detection.
- `scripts/install_baba_state_exporter.py`: installs or removes the Lua exporter.
- `scripts/read_baba_state.py`: prints the latest exported runtime state from
  save `[agent_state]`; `--path` can read an explicit JSON snapshot. Human
  output includes `edge_text_warnings` near the top, so even small `--limit`
  reads expose top/bottom/left/right/corner text that cannot be pushed off its
  locked axis. It also prints `hazard_break_opportunities` when an existing
  WIN rule may become reachable by removing an active hazard rule such as
  `skull is defeat`. Use `--at X,Y` to inspect exact occupants and active
  properties for a cell, especially after a move is blocked; this avoids
  confusing passable decoration such as `tile` with nearby `wall is stop`
  blockers hidden by truncated grouped output.
- `scripts/baba_app_status.py`: checks configured app name, the actual macOS
  process name, frontmost process, and runtime-state readability.
- `scripts/baba_send_keys.py`: low-level key sender. Prefer `--observe` so it
  delegates to `baba_try.py` and prints the resulting live-state delta.
- `scripts/parse_baba_level.py`: reads save state, `.ld`, `.l`, and `values.lua`,
  then prints rules, text map, object positions, and raw directions.
- `scripts/baba_try.py`: sends a short move segment, waits for state refreshes,
  and prints meaningful state deltas.
- `scripts/baba_action_check.py`: sends a short move segment and fails unless
  the declared expected rule/object/completion delta occurs. Expectations
  distinguish objects from word tiles: use `flag` for the physical object and
  `text_flag` for the FLAG text tile. After `check=fail`, reread live state
  before any undo. Do not treat `expanded_move_count` as safe undo count:
  blocked/no-op inputs can make `z*N` erase earlier successful progress. If the
  script prints `undo_expanded_steps_unsafe=true` or `preserved_progress=...`,
  continue from the real delta or use only `scripts/baba_undo.py --steps 1`
  with observation. Use
  `--expect-rule-kept` to protect current control/win rules, and
  `--forbid-rule-added` / `--forbid-rule-present` for bad accidental rules.
  Multi-step or pushed-text segments cannot rely on bare `--expect-moved`;
  use `--expect-moved-delta text_rock:-x` or
  `--expect-position text_rock 1,6` to declare the expected direction/endpoint.
  Contradictory rule expectations, such as the same rule in
  `--expect-rule-added` and `--expect-rule-removed`, fail before any key input.
  Completion checks for status `3` require an active WIN rule before the move
  unless the same segment declares `--expect-rule-added '<x> is win'`.
  Rule expectations automatically add relevant object/text names to focus, so
  protecting `baba is you` also shows `baba` / `text_baba` movement.
  Missing movement failures include a chain-push reminder: every pushed item
  must shift one tile, and the far-end cell must be free; corner/edge/pocket
  pushes are high-risk. They also remind agents to inspect exact blocked cells
  with `scripts/read_baba_state.py --at X,Y` instead of grepping truncated state
  summaries.
  Overlong segments fail closed with a suggested first segment and remaining
  segment; benchmark agents should split instead of using `--allow-long`.
  `--expect-completion` accepts either no value or a status value such as
  `--expect-completion 3`; winning checks print `observed_after_turn` for
  benchmark scoring.
- `scripts/baba_undo.py`: presses `z` and observes the resulting state delta.
  It defaults to safe single-step undo and rejects `--steps > 1` unless
  `--allow-multi-step` is explicit for manual rollback/debugging. Use it after
  rereading state, instead of calling `scripts/baba_action_check.py 'z'`.
- `scripts/baba_suggest_hypotheses.py`: prints candidate rule/action hypotheses.
  After its output, run at most one `--analyze`, then immediately choose one
  1-8 step `scripts/baba_action_check.py` segment with explicit `--expect-*`.
  When the live state turn is greater than 0, generated search commands include
  `--from-live-state` so route analysis starts from the current board, not the
  initial `.l` file. It also prints `edge_text_warnings` for text on room
  boundaries, such as `vertical_locked` top-row words and `corner_locked`
  corner words, so agents avoid impossible pushes. Visible hazard rules such as
  `skull is defeat` are ranked as high-value break candidates when an existing
  WIN rule is already active.
- `scripts/baba_search_route.py`: analyzes or searches small text-push routes.
  `--make-rule` accepts both `--make-rule flag is win` and
  `--make-rule "flag is win"`. In `selected_text`, labels such as
  `text_flag#0:flag@(x,y)` are text blocks, not physical objects.
- `scripts/baba_restart.py`: restarts the current level or world-map position.
- `scripts/baba_return_to_map.py`: returns from the current level or sub-map to
  its parent map with `esc,down,enter`.
- `scripts/baba_next_action.py`: read-only helper that classifies the current
  state as map/level and prints the safest next MCP/script action.
- `scripts/baba_map_route.py`: infers current map cursor and next-level route
  from live state when available, with save/map metadata fallback. This is the
  script fallback for MCP `navigate_next`.
- `scripts/baba_benchmark.py`: starts/resumes benchmark attempts, records
  pass-step scores, and maintains local per-agent run records. When the final
  action check prints `observed_after_turn=<N>`, pass `--game-turns <N>` to
  `--record-pass` so the score source remains `live_state_turn`. If
  `--force-new` replaces an unfinished active attempt, it prints and logs a
  strong warning because the previous level has no recorded pass.
- `runs/<run_id>/baba_route_plan.md`: temporary scratchpad automatically updated
  by `scripts/baba_action_check.py` with each short planned segment, expected
  delta, and observed outcome. It is not a known-route source.
- `scripts/baba_play_known_route.py`: prints or executes known routes from the
  current run's JSON route data, or an explicit `--routes` path.
- `scripts/baba_mcp_server.py`: thin MCP stdio wrapper over the core scripts.
- `lua/agent_state_export.lua`: optional Baba `Data/Lua` hook that stores live
  runtime units and rules in the save file after turns.
- `lua/agent_state_probe.lua`: minimal canary for checking Lua loading and
  save-file writes.

## Changelog

### 2026-05-01

- Added `--observe` to `scripts/baba_send_keys.py`. It delegates to
  `scripts/baba_try.py`, preserving the real key-input path while forcing the
  Snowman-style feedback loop: send input, wait for live state, print the
  meaningful delta.
- Documented `baba_send_keys.py` as a low-level helper rather than the preferred
  solving loop. Benchmark agents should still prefer MCP `check_moves` or
  `scripts/baba_action_check.py` with explicit expected deltas.

### 2026-04-27

- Split agent-facing instructions into `AGENTS.md`, leaving `README.md` focused
  on installation, configuration, MCP setup, and tool reference.
- Added `scripts/baba_app_status.py` and MCP `app_status` so agents recognize
  the normal macOS `Baba Is You` app-name versus `Chowdren` process-name split.
- Added root `start_benchmark.py` as the first-run agent handoff entry. It now
  checks local readiness, prints the rules primer, and refuses to start a level
  benchmark when the current state is a map/sub-map.
- Changed benchmark scoring to pass step count. `record_pass` prefers the live
  state `turn` value from the win event, falls back to expanded route length,
  and keeps wall-clock time only as auxiliary metadata.
- Updated run records and `baba_known_routes.json` metadata with
  `score_steps`, `score_source`, `last_score_steps`, and `best_score_steps`.
- Added `scripts/baba_return_to_map.py` and MCP `return_to_map` for the
  `esc,down,enter` return-to-parent-map menu flow.
- Added `scripts/baba_next_action.py` and MCP `suggest_next_action` so weaker
  agents can ask for the safest next action before acting.
- Hardened map navigation after `0level`: the default route now skips
  unreachable visible map nodes, prefers reachable unlocked levels such as
  `1level` at `(11,14)`, and accepts `--dry-run` as an explicit no-op.
- Added an efficiency protocol to `AGENTS.md` and `start_benchmark.py` so
  verbose agents stop exhaustive mental simulation and use short observable
  action segments instead.
- Tightened the efficiency protocol with one-observable-target loops, 5-line
  solving updates, and prompt guidance to avoid asking agents to expose long
  internal thinking.
- Added `scripts/baba_action_check.py` and MCP `check_moves` so agents validate
  hypotheses by declared state delta instead of thinking-token simulation.
- Hardened hypothesis handling: after `baba_suggest_hypotheses.py` or one
  `--analyze`, agents must move to a 1-8 step `baba_action_check.py` segment
  instead of continuing long rule-arrangement prose.
- Added generic dead-corner guidance as a reusable Baba mechanic, without
  turning it into level-specific coordinate hints.
- Added a hard failure constraint: after `check=fail`, agents must reread live
  state before undo/restart instead of explaining expected-but-unobserved moves.
- Added `scripts/baba_undo.py` and MCP `undo_moves`; multi-step undo is blocked
  by default because failed segments can include blocked/no-op inputs.
- Added rule invariant checks to `scripts/baba_action_check.py`: agents can now
  require `--expect-rule-kept 'wall is you'` and forbid accidental rules such as
  `--forbid-rule-added 'wall is stop'`.
- Added `baba_route_plan.md` as a temporary route scratchpad so planned short
  segments and their observed outcomes are externalized without becoming replay
  data.
- Documented project-level MCP setup for agents that support `.mcp.json`, plus
  the Codex CLI per-user MCP fallback.
- Hardened benchmark state handling: stale active attempts now block solving,
  `record_pass --level` refuses mismatched active records by default, and map
  navigation tells agents to start the benchmark after entering a level.
- Updated run templates so level notes and learned rules use step-score
  language, and the growth diary template avoids treating wall-clock time as
  the score.

### 2026-04-26

- Added `scripts/baba_try.py` for interactive state-delta experiments.
- Documented the state-reader-guided play loop in
  `docs/baba_state_guided_play_method.md`.
- Validated the interactive method on `189level / now what is this?`.
- Moved the default key interval into `baba_config.json` as `input_delay`; the
  checked-in default is `0.02` seconds.
- Added `scripts/baba_benchmark.py` for from-zero benchmark runs and moved known
  solved routes into run directories for separate replay use.
- Added config status detection for game files and installed exporter state.
- Added optional `scripts/baba_mcp_server.py` as a thin MCP wrapper.

## Current Limits

- Only supports macOS. Tested on Codex, ClaudeCode, OpenCode, and Claude-Agent-SDK.
- Static level parsing reads the initial level layout, not live per-turn object
  state after arbitrary moves.
- Live per-turn object positions require the optional Lua exporter.
- Input remains CGEvent-based; the Lua file only writes current game state into
  the save file.

## Safety Notes

- Do not grant broad permissions blindly. Only the process running these scripts
  needs Accessibility access.
- Do not rely on screenshot verification in the agent UI for this game; use save files,
  parser output, the live state exporter, or direct user observation.
- Keep `baba_config.json` local. It may contain machine-specific paths.
- If a Lua exporter experiment breaks startup, run
  `python3 scripts/install_baba_state_exporter.py --uninstall`, then restart the
  game.
