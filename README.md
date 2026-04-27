# Baba Is You Codex Control

Local macOS tooling for reading and controlling Baba Is You from Codex.

Only tested on Codex on macOS.

## Demo

[![Watch the Demo](https://img.youtube.com/vi/nju_P7gPk3U/0.jpg)](https://www.youtube.com/watch?v=nju_P7gPk3U)


## Why This Exists

This project reads local Baba Is You files and sends local macOS keyboard
events:

- Read state from local Baba files: save files tell us the current slot, world,
  map, and level; `.ld` and `.l` files describe level metadata, map layout, and
  object positions.
- Send input as low-level macOS keyboard events through
  `CGEventPost(kCGHIDEventTap)`.

The current tools do not edit save files to win levels.

## Requirements

- macOS.
- Steam version of Baba Is You installed locally.
- Python 3.
- Xcode Command Line Tools, for `clang`.
- macOS Accessibility permission for the app running these scripts, such as
  Codex or Terminal.
- Baba Is You should be running when sending keys.

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
python3 scripts/read_baba_state.py
python3 scripts/parse_baba_level.py --rules-only
```

If `state_exporter_installed=True`, skip the installer. That flag means the game
already has the Codex Lua exporter in place.

## Configuration

The repo does not store machine-specific paths. First run creates a local
`baba_config.json` from `baba_config.example.json` and stops so you can review
it:

```bash
python3 scripts/parse_baba_level.py
```

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

`baba_config.json` is ignored by git. Use `BABA_CONFIG=/path/to/config.json` or
`--config /path/to/config.json` for a different config file.
Adjust `input_delay` if another machine needs a slower or faster key interval.
The generated config refreshes `game_files_found` and
`state_exporter_installed` from the local filesystem. Treat
`state_exporter_installed=true` as the "game is already modded" flag and do not
rerun the exporter installer unless you are intentionally repairing it.
Set `current_run_id` to the current agent/model run folder, such as
`001_codex_gpt55` or `002_claude_sonnet`.

Refresh and inspect local config status:

```bash
python3 scripts/baba_config.py
python3 scripts/baba_config.py --set-current-run-id 001_codex_gpt55
```

## Basic Usage

Read the current level:

```bash
python3 scripts/parse_baba_level.py
```

Read a specific level:

```bash
python3 scripts/parse_baba_level.py --world baba --level 1level
```

Send moves:

```bash
python3 scripts/baba_send_keys.py 'right,left,up'
```

`baba_send_keys.py` defaults to the configured `input_delay`, currently 0.02
seconds in `baba_config.example.json`, and a 90ms CoreGraphics key hold. Some
machines or long routes may need a slower `input_delay`, and some route notes
may specify a larger hold such as `--hold-ms 140`.

Restart the current level or world-map position:

```bash
python3 scripts/baba_restart.py
```

Install the live runtime state exporter:

```bash
python3 scripts/install_baba_state_exporter.py
```

By default this installs only `Data/Lua/codex_state_export.lua`, because Baba
already loads Lua files from that directory. It does not patch `modsupport.lua`
or `syntax.lua`. Restart Baba Is You after installing, then read the latest
runtime state from the current save file's `[codex_state]` group:

```bash
python3 scripts/read_baba_state.py
```

When entering a level from a fresh game launch, the menu-to-map transition can
swallow immediate input. Use `enter,enter`, wait about 3 seconds, then send
`enter` again before expecting level state.

Before installing the full exporter, use the minimal probe to verify Baba's
`Data/Lua` loading and `world_data.txt` write path:

```bash
python3 scripts/install_baba_state_exporter.py --probe
python3 scripts/read_baba_probe.py
```

The probe writes only the `[codex_probe]` section in
`Data/Worlds/<world>/world_data.txt`. Remove it with:

```bash
python3 scripts/install_baba_state_exporter.py --probe --uninstall
```

Send one or more moves and wait for the exporter after each move:

```bash
python3 scripts/baba_step.py 'right,up'
```

Send a short hypothesis segment and print only the meaningful state delta:

```bash
python3 scripts/baba_try.py 'left*3'
```

Detect a route from the current world map cursor to the next unlocked level:

```bash
python3 scripts/baba_map_route.py
```

Execute that detected route:

```bash
python3 scripts/baba_map_route.py --execute
```

Search for a text-rule route, such as building `FLAG IS WIN`:

```bash
python3 scripts/baba_search_route.py --make-rule flag is win
```

Run the benchmark entry for a new agent handoff:

```bash
python3 scripts/baba_benchmark.py
```

Benchmark mode starts a
fresh state-guided attempt, times the agent's learning/solving process, and
appends local notes under `runs/<number_agent_model>/`. Set `current_run_id` in
`baba_config.json` or pass `--run-id 002_agent_model` for another agent. Only
the root `runs/*.template.md` files are intended for Git.

Recommended setup for a benchmark agent:

```bash
python3 scripts/baba_config.py --set-current-run-id 002_agent_model
python3 scripts/baba_benchmark.py
python3 scripts/read_baba_state.py
python3 scripts/parse_baba_level.py --rules-only
```

Then solve interactively with short state-readable experiments:

```bash
python3 scripts/baba_try.py '<short move segment>'
```

After the level is solved, record the benchmark result:

```bash
python3 scripts/baba_benchmark.py --record-pass --moves '<verified full route>' --note '<short summary>'
```

## Optional MCP Server

Agents that support MCP can use the dependency-free stdio wrapper instead of
remembering shell commands. The MCP server is intentionally thin: it only calls
the existing scripts and returns command, exit code, stdout, and stderr.

Example MCP command:

```bash
python3 scripts/baba_mcp_server.py
```

Example MCP config shape:

```json
{
  "mcpServers": {
    "baba-is-you": {
      "command": "python3",
      "args": ["/path/to/baba-is-agent/scripts/baba_mcp_server.py"]
    }
  }
}
```

Exposed tools:

- `config_status`
- `set_current_run_id`
- `start_benchmark`
- `read_state`
- `parse_rules`
- `try_moves`
- `restart_level`
- `map_route`
- `play_known_route`
- `record_pass`

Benchmark rules are unchanged: start from the current state, do not use
run-local `baba_known_routes.json` as a solution source, and record pass only
after completion status becomes `3`.
Only `try_moves`, `restart_level` without `dry_run`, `map_route` with
`execute=true`, and `play_known_route` with `execute=true` send game input.

Prompt for another agent:

```text
根据第一性原理，从当前 Baba Is You 状态开始做一次独立 benchmark。
不要使用当前 run 目录里的 baba_known_routes.json 作为解法来源。
先运行 python3 scripts/baba_config.py 检查 game_files_found、state_exporter_installed 和 current_run_id。
如果 current_run_id 不是你的 runs/<number_agent_model> 目录名，先用 python3 scripts/baba_config.py --set-current-run-id <number_agent_model> 设置。
然后运行 python3 scripts/baba_benchmark.py 开始计时。
使用 python3 scripts/read_baba_state.py、python3 scripts/parse_baba_level.py --rules-only 和 python3 scripts/baba_try.py '<moves>' 交互式缩小搜索空间。
通关后运行 python3 scripts/baba_benchmark.py --record-pass --moves '<verified full route>' --note '<short summary>' 记录成绩。
```

See `docs/baba_state_guided_play_method.md` for the interactive
state-reader-guided workflow and when to use short experiments instead of full
route search.

## Tools

- `scripts/baba_config.py`: shared config loader, first-run config creation, and
  local game/exporter status detection.
- `scripts/parse_baba_level.py`: reads save state, `.ld`, `.l`, and `values.lua`, then
  prints rules, a text map, object positions, and raw object directions for
  `MOVE` reasoning.
- `scripts/baba_send_keys.py`: compiles and calls the CoreGraphics helper by default.
- `scripts/baba_cgevent_keys.c`: tiny macOS key-event sender.
- `scripts/baba_map_route.py`: infers current map cursor and next-level route
  from live state when available, with save/map metadata fallback.
- `scripts/baba_search_route.py`: generic macro-push searcher for building text
  rules from the current level state.
- `runs/<current_run_id>/baba_known_routes.json`: local machine-readable known
  routes for replay.
- `scripts/baba_play_known_route.py`: prints or executes known routes from the
  current run's JSON route data, or an explicit `--routes` path.
- `scripts/baba_benchmark.py`: handoff entry that starts a from-zero benchmark
  attempt and maintains local per-agent `runs/<number_agent_model>/` records.
- `lua/codex_state_export.lua`: optional Baba `Data/Lua` hook that stores live
  runtime units and rules in the save file after turns.
- `lua/codex_state_probe.lua`: minimal canary that checks Baba can load a
  `Data/Lua` file and write `[codex_probe]` into `world_data.txt`.
- `scripts/install_baba_state_exporter.py`: installs or removes the Lua exporter.
- `scripts/read_baba_probe.py`: reads the minimal probe result from
  `world_data.txt`.
- `scripts/read_baba_state.py`: prints the latest exported runtime state from
  the save group, with legacy JSON fallback.
- `scripts/baba_step.py`: sends moves one at a time and waits for fresh live
  state after each turn.
- `scripts/baba_try.py`: sends a short move segment, waits for state refreshes,
  and prints rules/units/completion changes instead of a full state dump.
- `scripts/baba_mcp_server.py`: optional dependency-free MCP stdio wrapper
  around config, benchmark, state, rules, move, restart, map-route,
  known-route, and pass-record scripts.

## Changelog

### 2026-04-26

- Added `scripts/baba_try.py` for interactive state-delta experiments: send a
  short move segment, wait for live state refreshes, and inspect only meaningful
  rules, unit, and completion changes.
- Documented the state-reader-guided play loop in
  `docs/baba_state_guided_play_method.md`, including when to use short
  experiments instead of heavier route search.
- Validated the interactive method on `189level / now what is this?`; the same
  workflow is usable by smaller models because each step has a narrow,
  state-readable checkpoint.
- Moved the default key interval into `baba_config.json` as `input_delay`
  after testing the current level; the checked-in default is `0.02` seconds.
- Added `scripts/baba_benchmark.py` for from-zero state-guided benchmark runs,
  and moved known solved routes into each run directory for separate replay use.
- Added config status detection so generated `baba_config.json` records whether
  Baba game files exist and whether the Lua state exporter is already installed.
- Added optional `scripts/baba_mcp_server.py` as a thin MCP wrapper over the
  existing scripts, keeping CLI scripts as the source of truth.

## Current Limits

- Only tested on Codex on macOS.
- Static level parsing reads the initial level layout, not live per-turn object
  state after arbitrary moves.
- Live per-turn object positions require the optional Lua exporter. Input remains
  CGEvent-based; the Lua file only writes current game state into the save file.

## Safety Notes

- Do not grant broad permissions blindly. Only the process running these scripts
  needs Accessibility access.
- Do not rely on screenshot verification in Codex for this game; use save files,
  parser output, the live state exporter, or direct user observation.
- Keep `baba_config.json` local. It may contain machine-specific paths.
- If a Lua exporter experiment breaks startup, run
  `python3 scripts/install_baba_state_exporter.py --uninstall`, then restart the
  game. The default installer avoids core-script patching; `--patch-loader` and
  `--patch-command-loader` are advanced recovery/debug switches only.
