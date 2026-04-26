# Baba Is You Situation Awareness

This repo lets Codex read local Baba Is You files and send local macOS key events. Use this file first when taking over a play session.

## Current Goal

Continue playing the current save, one level at a time:

1. Confirm the real current state from save files.
2. Enter the next level from the map only after verifying the real cursor.
3. After entering any new level, read and restate its initial active rules before solving.
4. Run the rule-mobility analysis: identify which initial text rules can actually be pushed, and which pushes preserve the current `YOU` rule.
5. Solve by combining parser output with short in-game feedback loops.
6. Verify success from save status, not from command exit codes.

## Important User Preferences

- Start answers with `根据第一性原理...`.
- Do not use web search for solutions. Think locally and use game feedback.
- Use screenshots only when local parsing and game behavior conflict; screenshots are token-expensive.
- Use file coordinates only. The file coordinate system includes an outer border; the actual movable range is `x=1..width-2`, `y=1..height-2`.
- Keep `runs/baba_learned_rules.md` generic. Put level-specific routes and notes in `runs/baba_level_notes.md`.

## Key Commands

Read current level:

```bash
python3 scripts/parse_baba_level.py
```

Read only the initial rules:

```bash
python3 scripts/parse_baba_level.py --rules-only
```

Read a specific level:

```bash
python3 scripts/parse_baba_level.py --world baba --level 6level
```

Detect map route:

```bash
python3 scripts/baba_map_route.py
python3 scripts/baba_map_route.py 6level
```

When `--execute` succeeds, `baba_map_route.py` now automatically prints the entered level's initial active rules. If you enter a level manually with `baba_send_keys.py`, immediately run `python3 scripts/parse_baba_level.py --rules-only` and restate those rules in chat before solving.

Send keys:

```bash
python3 scripts/baba_send_keys.py 'right,left,up'
```

Install live state exporter:

```bash
python3 scripts/install_baba_state_exporter.py
```

Restart Baba Is You after installing, then read live exported state:

```bash
python3 scripts/read_baba_state.py
```

Restart current level when stuck:

```bash
python3 scripts/baba_restart.py
```

This same restart helper works both inside a level and on the world map.

Known route lookup:

```bash
PYTHONPATH=scripts python3 runs/baba_play_known_route.py --list
PYTHONPATH=scripts python3 runs/baba_play_known_route.py --level 2level
```

Constrained route search:

```bash
python3 scripts/baba_search_route.py --analyze
python3 scripts/baba_search_route.py --make-rule flag is win
```

This script is generic. It uses Level 6's reusable method: derive blockers from
active rules, search only relevant movable text, preserve YOU, and widen
`--pattern-margin` only if the small-window search fails.

## Current Save Snapshot

At the time this handoff was written:

- `slot=2`
- `world=baba`
- `Previous=209level`
- `leveltree=106level,177level`
- Completed: `0level=3`, `1level=3`, `2level=3`, `3level=3`, `4level=3`, `5level=3`, `6level=3`, `10level=3`, `20level=3`, `90level=3`, `93level=3`, `209level=3`, `212level=3`
- Uncompleted/unlocked seen in save: `8level=2`, `15level=2`, `189level=2`, `210level=2`, `211level=2`, `177level=2`

The player has just completed `209level / lock` inside `177level / 1. the lake`; `15level`, `8level`, `210level`, `211level`, `189level`, and `177level` are still unlocked. Before executing any map route, re-run:

```bash
python3 scripts/baba_map_route.py
```

At the time of this update it reported `target=15level`, `cursor=(16, 7) source=levelsurrounds`, and `moves=left,enter`.

## Files To Know

- `README.md`: repo overview.
- `scripts/parse_baba_level.py`: static parser for current/specific levels.
- `scripts/baba_send_keys.py`: verified CGEvent key sender.
- `scripts/baba_map_route.py`: map route detector; good but still verify cursor source.
- `lua/codex_state_export.lua`: optional live-state exporter loaded by Baba from `Data/Lua`.
- `scripts/install_baba_state_exporter.py`: installs/uninstalls the exporter.
- `scripts/read_baba_state.py`: reads the current exported JSON state.
- `runs/baba_learned_rules.md`: generic rules only.
- `runs/baba_level_notes.md`: level-specific routes and notes.
- `docs/baba_level_parsing_method.md`: parser method and coordinate notes.
- `dev/baba_control_handoff.md`: longer historical handoff.

## Critical Rules

- `frontmost=Chowdren` only proves the game process is focused; it does not prove movement or success.
- A level is complete only when its save field becomes `3`.
- Use the default `0.5s` delay between key presses. For long routes, keep the cgevent hold at least `90ms`; route notes may specify a higher hold such as `140ms`.
- Expand `AND` rules when restating initial rules, e.g. `BABA IS YOU AND SINK` means both `BABA IS YOU` and `BABA IS SINK`.
- Text blocks are pushable by default.
- `B` in parser output means real `baba`; `M` means `brick`.
- Do not treat the outer border as walkable.
- If a route fails, restart with `python3 scripts/baba_restart.py`, then try a shorter or corrected route.
- If `scripts/read_baba_state.py` has fresh output, prefer it over static `.l/.ld` parsing
  for turn-by-turn object and text positions.

## Recent Proven Routes

See `runs/baba_level_notes.md` for details. Most recent:

```text
209level / lock:
up,left*3,down,right*9,right*2,up,right*3,down,left*7,up,left,down*5,right,down,left*3,down,left,up,right*3,up,left,up,right,up*3,right*6,up,right,down*5
```

Use `--delay 0.5 --hold-ms 140` for this route. It completed with `209level=3`.
