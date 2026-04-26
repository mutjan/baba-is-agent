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
  "input_delay": 0.02
}
```

`baba_config.json` is ignored by git. Use `BABA_CONFIG=/path/to/config.json` or
`--config /path/to/config.json` for a different config file.
Adjust `input_delay` if another machine needs a slower or faster key interval.

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

See `docs/baba_state_guided_play_method.md` for the interactive
state-reader-guided workflow and when to use short experiments instead of full
route search.

## Tools

- `scripts/baba_config.py`: shared config loader and first-run config creation.
- `scripts/parse_baba_level.py`: reads save state, `.ld`, `.l`, and `values.lua`, then
  prints rules, a text map, object positions, and raw object directions for
  `MOVE` reasoning.
- `scripts/baba_send_keys.py`: compiles and calls the CoreGraphics helper by default.
- `scripts/baba_cgevent_keys.c`: tiny macOS key-event sender.
- `scripts/baba_map_route.py`: infers current map cursor and next-level route from save
  and map metadata.
- `scripts/baba_search_route.py`: generic macro-push searcher for building text
  rules from the current level state.
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
