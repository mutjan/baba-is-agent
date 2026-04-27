# Baba Is You Situation Awareness

This file is a lightweight current-save handoff. The canonical agent objective,
operating method, benchmark rules, and game primer live in `AGENTS.md`.

## Current Save Snapshot

Last local dry-run of `start_benchmark.py` saw:

- `slot=0`
- `world=baba`
- `Previous=3level`
- level name: `out of reach`

This is orientation only. The game may have moved since this file was written.
Before solving or navigating, re-read live state:

```bash
python3 scripts/read_baba_state.py
python3 scripts/parse_baba_level.py --rules-only
```

If the player is on the map instead of inside a level, use MCP `navigate_next`
or script fallback:

```bash
python3 scripts/baba_map_route.py
```

## Files To Know

- `AGENTS.md`: canonical agent target, operation method, benchmark rules, and
  game primer.
- `README.md`: installation, configuration, MCP setup, and tool reference.
- `start_benchmark.py`: root first-run handoff entry for newly assigned agents.
- `scripts/baba_mcp_server.py`: thin MCP stdio wrapper over the core scripts.
- `scripts/baba_app_status.py`: read-only app/process/status check. Use it
  instead of checking only for a `Baba Is You` process name.
- `scripts/baba_next_action.py`: read-only next-action classifier for weak or
  newly assigned agents.
- `scripts/baba_config.py`: local config creator/status refresher. It updates
  `game_files_found` and `state_exporter_installed` in ignored config.
- `scripts/read_baba_state.py`: reads the current exported save-group state,
  with legacy JSON fallback.
- `scripts/parse_baba_level.py`: static parser for current/specific levels.
- `scripts/baba_try.py`: sends a short action segment and prints state deltas.
- `scripts/baba_restart.py`: restarts the current level or map position.
- `scripts/baba_return_to_map.py`: returns from the current level or sub-map to
  its parent map.
- `scripts/baba_map_route.py`: route detector for world map navigation; it
  prefers the live-state cursor when available.
- `scripts/baba_benchmark.py`: starts/stops timing and updates run records.
- `runs/*.template.md`: publishable templates for per-agent run records.
- `docs/baba_state_guided_play_method.md`: reusable explanation of the
  state-reader-guided play loop.

## Critical Evidence Notes

- `Baba Is You` is the app/bundle name; the actual macOS process commonly
  appears as `Chowdren`. A raw `processes contains "Baba Is You"` check can be
  false even while the game is running.
- `frontmost=Chowdren` only proves the game process is focused; it does not
  prove movement or success.
- A level is complete only when its save field becomes `3`.
- Benchmark score is pass step count. Prefer live-state `turn`; wall-clock time
  is auxiliary only.
- Use the configured `input_delay`; the checked-in default is `0.02s`.
- Text blocks are pushable by default because `TEXT IS PUSH` is a base rule.
- If `scripts/read_baba_state.py` has fresh output, prefer it over static
  `.l/.ld` parsing for turn-by-turn object and text positions.
- On the big map after `0level`, do not chase the visible but unreachable lake
  map node at `(16,10)`; use `navigate_next`/`map_route`, which should target
  `1level` at `(11,14)` while only the short path from `(10,16)` is open.
- If Lua exporter work causes startup errors, run
  `python3 scripts/install_baba_state_exporter.py --uninstall` and restart Baba
  before doing more experiments.
