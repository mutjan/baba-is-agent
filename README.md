# Baba Is You Codex Control

Local macOS tooling for reading and controlling Baba Is You from Codex.

Only tested on Codex on macOS.

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
- macOS Accessibility permission for the app running these scripts, such as
  Codex or Terminal.
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
already has the Codex Lua exporter in place.

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
`001_codex_gpt55` or `002_claude_sonnet`:

```bash
python3 scripts/baba_config.py --set-current-run-id 001_codex_gpt55
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

Codex CLI currently uses the user's Codex config, so install it per user:

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
- `return_to_map`
- `navigate_next`
- `map_route`
- `play_known_route`
- `record_pass`

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
  the save group, with legacy JSON fallback.
- `scripts/baba_app_status.py`: checks configured app name, the actual macOS
  process name, frontmost process, and save-state readability.
- `scripts/parse_baba_level.py`: reads save state, `.ld`, `.l`, and `values.lua`,
  then prints rules, text map, object positions, and raw directions.
- `scripts/baba_try.py`: sends a short move segment, waits for state refreshes,
  and prints meaningful state deltas.
- `scripts/baba_action_check.py`: sends a short move segment and fails unless
  the declared expected rule/object/completion delta occurs.
- `scripts/baba_restart.py`: restarts the current level or world-map position.
- `scripts/baba_return_to_map.py`: returns from the current level or sub-map to
  its parent map with `esc,down,enter`.
- `scripts/baba_next_action.py`: read-only helper that classifies the current
  state as map/level and prints the safest next MCP/script action.
- `scripts/baba_map_route.py`: infers current map cursor and next-level route
  from live state when available, with save/map metadata fallback.
- `scripts/baba_benchmark.py`: starts/resumes benchmark attempts, records
  pass-step scores, and maintains local per-agent run records.
- `scripts/baba_play_known_route.py`: prints or executes known routes from the
  current run's JSON route data, or an explicit `--routes` path.
- `scripts/baba_mcp_server.py`: thin MCP stdio wrapper over the core scripts.
- `lua/codex_state_export.lua`: optional Baba `Data/Lua` hook that stores live
  runtime units and rules in the save file after turns.
- `lua/codex_state_probe.lua`: minimal canary for checking Lua loading and
  save-file writes.

## Changelog

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
- Added generic dead-corner guidance as a reusable Baba mechanic, without
  turning it into level-specific coordinate hints.
- Documented project-level MCP setup for agents that support `.mcp.json`, plus
  the current Codex per-user MCP fallback.
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

- Only tested on Codex on macOS.
- Static level parsing reads the initial level layout, not live per-turn object
  state after arbitrary moves.
- Live per-turn object positions require the optional Lua exporter.
- Input remains CGEvent-based; the Lua file only writes current game state into
  the save file.

## Safety Notes

- Do not grant broad permissions blindly. Only the process running these scripts
  needs Accessibility access.
- Do not rely on screenshot verification in Codex for this game; use save files,
  parser output, the live state exporter, or direct user observation.
- Keep `baba_config.json` local. It may contain machine-specific paths.
- If a Lua exporter experiment breaks startup, run
  `python3 scripts/install_baba_state_exporter.py --uninstall`, then restart the
  game.
