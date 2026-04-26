# Baba Is You Situation Awareness

This repo lets Codex read local Baba Is You files and send local macOS key events. Use this file first when taking over a play session.

## Current Goal

Continue playing the current save, one level at a time:

1. Confirm the real current state from save files.
2. Enter the next level from the map only after verifying the real cursor.
3. After entering any new level, read and restate its initial active rules before solving.
4. Run the rule-mobility analysis: identify which initial text rules can actually be pushed, and which pushes preserve the current `YOU` rule.
5. Solve by combining parser output with short in-game feedback loops. Prefer a
   meaningful move segment such as `left*3` over mechanical one-step polling
   when the expected state change is clear.
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

This installs only `Data/Lua/codex_state_export.lua` by default. It deliberately
does not patch `Data/modsupport.lua` or `Data/syntax.lua`; those switches exist
only for advanced debugging. Restart Baba Is You after installing, then read the
state stored in the current save file's `[codex_state]` group:

```bash
python3 scripts/read_baba_state.py
```

After a fresh launch, enter a level with `enter,enter`, wait about 3 seconds for
the menu-to-map transition, then send `enter` again. Reading state too early can
correctly show the world map rather than the level.

Safer canary before the full exporter:

```bash
python3 scripts/install_baba_state_exporter.py --probe
python3 scripts/read_baba_probe.py
```

The probe only writes `[codex_probe]` in `Data/Worlds/<world>/world_data.txt`.
Remove it with:

```bash
python3 scripts/install_baba_state_exporter.py --probe --uninstall
```

For turn-by-turn feedback, send moves through the state-aware wrapper:

```bash
python3 scripts/baba_step.py 'right,up'
```

For interactive play, send a short hypothesis segment and print only the state
delta:

```bash
python3 scripts/baba_try.py 'left*3'
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

At the time this handoff was last updated:

- `slot=2`
- `world=baba`
- `Previous=15level`
- `leveltree=106level,177level`
- Completed: `0level=3`, `1level=3`, `2level=3`, `3level=3`, `4level=3`, `5level=3`, `6level=3`, `10level=3`, `20level=3`, `90level=3`, `93level=3`, `189level=3`, `209level=3`, `212level=3`
- Uncompleted/unlocked seen in save: `8level=2`, `15level=2`, `210level=2`, `211level=2`, `177level=2`

The player has completed `189level / now what is this?` and the current save
now points at `15level / novice locksmith`. Before solving or executing any map
route, re-run:

```bash
python3 scripts/read_baba_state.py
python3 scripts/parse_baba_level.py --rules-only
```

If the player is on the map instead of inside a level, use
`python3 scripts/baba_map_route.py` to re-detect the real cursor.

## Files To Know

- `README.md`: repo overview.
- `scripts/parse_baba_level.py`: static parser for current/specific levels.
- `scripts/baba_send_keys.py`: verified CGEvent key sender.
- `scripts/baba_map_route.py`: map route detector; good but still verify cursor source.
- `lua/codex_state_export.lua`: optional live-state exporter loaded by Baba from `Data/Lua`.
- `lua/codex_state_probe.lua`: minimal canary for `Data/Lua` loading and `world_data.txt` writes.
- `scripts/install_baba_state_exporter.py`: installs/uninstalls the exporter.
- `scripts/read_baba_probe.py`: reads the canary result from `world_data.txt`.
- `scripts/read_baba_state.py`: reads the current exported save-group state, with legacy JSON fallback.
- `scripts/baba_step.py`: sends each move and waits for the live state to update.
- `scripts/baba_try.py`: sends a short action segment and prints state deltas for
  rules, moved units, disappeared units, and completion status.
- `runs/baba_learned_rules.md`: generic rules only.
- `runs/baba_level_notes.md`: level-specific routes and notes.
- `docs/baba_level_parsing_method.md`: parser method and coordinate notes.
- `docs/baba_state_guided_play_method.md`: state-reader-guided play loop and
  script-vs-Markdown boundary.
- `dev/baba_control_handoff.md`: longer historical handoff.

## Critical Rules

- `frontmost=Chowdren` only proves the game process is focused; it does not prove movement or success.
- A level is complete only when its save field becomes `3`.
- Use the configured `input_delay` between key presses. The current default is
  `0.02s`; if another machine drops inputs, raise `input_delay` in
  `baba_config.json`. For long routes, keep the cgevent hold at least `90ms`;
  route notes may specify a higher hold such as `140ms`.
- Expand `AND` rules when restating initial rules, e.g. `BABA IS YOU AND SINK` means both `BABA IS YOU` and `BABA IS SINK`.
- If Lua exporter work causes startup errors, immediately run
  `python3 scripts/install_baba_state_exporter.py --uninstall` and restart Baba
  before doing more experiments.
- Text blocks are pushable by default.
- `B` in parser output means real `baba`; `M` means `brick`.
- Do not treat the outer border as walkable.
- If a route fails, restart with `python3 scripts/baba_restart.py`, then try a shorter or corrected route.
- If `scripts/read_baba_state.py` has fresh output, prefer it over static `.l/.ld` parsing
  for turn-by-turn object and text positions.
- When using the live exporter, stop each move segment at a meaningful
  checkpoint: rules added/removed, key text moved into place, object removed, or
  level completion. Use `baba_try.py` for this concise delta.

## Recent Proven Routes

See `runs/baba_level_notes.md` for details. Most recent:

```text
209level / lock:
up,left*3,down,right*9,right*2,up,right*3,down,left*7,up,left,down*5,right,down,left*3,down,left,up,right*3,up,left,up,right,up*3,right*6,up,right,down*5
```

Use `--delay 0.5 --hold-ms 140` for this route. It completed with `209level=3`.

`189level / now what is this?`:

```text
left*3,up*7,right*3,down,right*2,up,left*3,down,left,up*2,left,down,left,up,left
```

It breaks `FLAG IS STOP`, builds `FLAG IS WIN` around the fixed upper `IS`, and
completed with `189level=3`.
