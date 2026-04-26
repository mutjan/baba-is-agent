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
  "app_name": "Baba Is You"
}
```

`baba_config.json` is ignored by git. Use `BABA_CONFIG=/path/to/config.json` or
`--config /path/to/config.json` for a different config file.

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

`baba_send_keys.py` defaults to a 0.5 second delay between keys and a 90ms
CoreGraphics key hold because faster or shorter input can miss restart
confirmation or long routes in Baba Is You. Some route notes may specify a
larger hold, such as `--hold-ms 140`.

Restart the current level or world-map position:

```bash
python3 scripts/baba_restart.py
```

Install the live runtime state exporter:

```bash
python3 scripts/install_baba_state_exporter.py
```

Then restart Baba Is You so the game loads `Data/Lua/codex_state_export.lua`.
After each level start or turn, read the latest runtime state:

```bash
python3 scripts/read_baba_state.py
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
- `lua/codex_state_export.lua`: optional Baba `Data/Lua` hook that exports live
  runtime units and rules to JSON after turns.
- `scripts/install_baba_state_exporter.py`: installs or removes the Lua exporter.
- `scripts/read_baba_state.py`: prints the latest exported runtime state.

## Current Limits

- Only tested on Codex on macOS.
- Static level parsing reads the initial level layout, not live per-turn object
  state after arbitrary moves.
- Live per-turn object positions require the optional Lua exporter. Input remains
  CGEvent-based; the Lua file only writes current game state.

## Safety Notes

- Do not grant broad permissions blindly. Only the process running these scripts
  needs Accessibility access.
- Do not rely on screenshot verification in Codex for this game; use save files,
  parser output, the live state exporter, or direct user observation.
- Keep `baba_config.json` local. It may contain machine-specific paths.
