# Baba Agent Contract

This project is not about replaying known routes. Its purpose is for the agent
to start from the real current state, learn interactively, solve Baba Is You
levels, and leave verifiable benchmark records.

## Goals And Success Criteria

- At every handoff, first confirm the real state: configuration, current save,
  current level, initial rules, and whether the game is on a map.
- The benchmark measures from-zero learning and solving ability. Do not use
  `baba_known_routes.json` in the current run directory as a solution source.
- There is exactly one hard proof of completion: the corresponding level save
  completion status becomes `3`.
- The primary benchmark score is `score_steps`, not wall-clock time. Wall-clock
  time is only auxiliary metadata.
- After each solved level, record that level's `score_steps` and update the
  current run directory's record files.
- Reply to the user in the user's language. For this repository, every
  collaboration reply should start with `根据第一性原理……` by default.

## Collaboration Output Rules

- First confirm the real goal, constraints, and success criteria. Do not apply
  conventions by habit.
- If the goal, success criteria, or risk boundary is unclear and would affect
  implementation direction, ask the user first.
- If the goal is clear but the current path is not the simplest, lowest-risk,
  verifiable option, state the better alternative directly.
- When a decision is needed, cover the main possibilities according to MECE.
- Keep output concise by default: conclusion, key reason, changes, verification.
- In this project, first-principles thinking means finding the shortest
  verifiable feedback loop. It does not mean exhaustive route enumeration or a
  long proof.

## Preferred Entry Point

After a fresh clone or a new agent handoff, run this from the repository root:

```bash
python3 start_benchmark.py --run-id 001_agent_model
```

If MCP is available, prefer the MCP `start_benchmark` tool instead of directly
calling the raw script. The raw script is the fallback and debugging entry point.

Dry-run check:

```bash
python3 start_benchmark.py --dry-run --skip-primer --no-inspect
```

## MCP-First Workflow

When MCP tools are available, use this order by default:

1. `app_status`, to confirm the game process and state files are readable.
2. `suggest_next_action`, when the next step is uncertain.
3. `inspect_state`.
4. `rule_goal_scan`, when the question is "which rule should change first?"
   and the agent needs the next minimal rule delta.
5. `set_current_run_id`, only when the current run id is wrong or empty.
6. `start_benchmark`.
7. `check_moves`, after first declaring an expected delta and then verifying a
   short action segment with the script.
8. `try_moves`, only when debugging raw deltas or when there is no clear
   expectation yet.
9. `restart_level`, when an experiment has damaged the state or a clean
   checkpoint is needed.
10. `undo_moves`, when the previous `check_moves` failed and the state should
    return to just before that failed segment.
11. `return_to_map`, when leaving a level or sub-map for its parent map.
12. `navigate_next`, when the current state is a world map or overworld.
13. `record_pass`, only after completion status is already `3`.

Only fall back to `python3 scripts/...` when MCP is unavailable or when debugging
an MCP wrapper, and say why.

MCP tool names are not script names. Do not guess script files from tool names.
In particular, `navigate_next` exists only in MCP. The script fallback is
`python3 scripts/baba_map_route.py --execute`. There is no
`scripts/baba_navigate_next.py` in this project.

## Game Process Identification

- On macOS, the configured app/bundle name is usually `Baba Is You`, but the
  actual foreground process may be the engine name `Chowdren`.
- Do not treat `System Events` checks such as `processes contains "Baba Is You"`
  as the only running-state test; they can be false negatives.
- Use MCP `app_status` or `python3 scripts/baba_app_status.py`. It is normal to
  see `running_process_detected=True` and `running_process_name=Chowdren`.
- `frontmost_process=Chowdren` only means the window is focused. Whether state is
  readable and movement works must still be confirmed by `runtime_state_available`,
  `inspect_state`, and later `check_moves` results.

## Maps Versus Normal Levels

- If the current level is a world map or overworld, such as `106level` or
  `177level`, do not solve it as a normal Baba puzzle.
- A map state having no Baba object is not an error. The controllable object on
  maps is the live-state `cursor`, controlled by `cursor is select`.
- On maps, prefer MCP `navigate_next` to enter an unfinished level. The fixed
  script fallback is `python3 scripts/baba_map_route.py --execute`.
- `navigate_next` / `baba_map_route.py --execute` only enters a level; it does
  not start scoring. After entering a normal level, run MCP `start_benchmark` or
  `python3 start_benchmark.py` before solving.
- Do not choose a target by guessing from all visible `level` cells. Maps show
  many currently unreachable levels. Use `suggest_next_action`'s `route_target`
  / `route_moves`, or `map_route` output.
- After passing `0level` on the main map, the typical next level is `1level` at
  `(11,14)`. From `0level` coordinate `(10,16)`, the route is
  `right,up,up,enter`.
- When a level or sub-map needs to return to the parent map, use
  `return_to_map`. The underlying keys are `esc,down,enter`.

Do not start a level benchmark while on a map or sub-map. If `start_benchmark`
detects a map, it will ask for `navigate_next` first so the map is not scored as
a normal level.

If `start_benchmark` reports `active_state_mismatch=true`, the current live
level differs from the unfinished active benchmark file. Do not keep solving,
and do not bypass it with `--record-pass --level ...`. Follow the script's
`--force-new` repair guidance before moving.

## Baba Rule Basics

- Rules are usually made of visible text in the form `NOUN IS PROPERTY`.
- `YOU` marks controllable objects. `WIN` marks victory objects. `STOP` blocks
  movement. `DEFEAT` destroys `YOU`.
- When `SHUT` and `OPEN` touch, both are removed, such as a key opening a door.
- Text is pushable by default. `TEXT IS PUSH` is a base rule and may be active
  even when it is not explicitly visible in the level.
- `PUSH` means that when a `YOU` object moves in a direction, it may push the
  corresponding object or text one cell forward, provided the whole pushed chain
  has empty space behind its far end.
- If the far end of the pushed chain is `STOP`, the map boundary, or an
  unpushable blocker, the push does not happen.
- Before every push of a `PUSH` object or text, explicitly check chain pushing:
  every object/text in the chain moves one cell, and the far-end cell must be
  free. Do not look only at the first contacted cell.
- For boundaries, corners, and enclosed regions, prefer
  `python3 scripts/baba_spatial_diagnostics.py --actor baba`. Pushable units in
  corners geometrically have no push direction; pushable units on edges usually
  can only move along the edge axis. `--actor` defaults to `baba`, but can be set
  to `--actor wall` or another object.
- Moving text can create or break rules. Moving `IS`, `YOU`, `WIN`, `STOP`,
  `PUSH`, `OPEN`, `SHUT`, or noun text is often the core of a solution.
- Around `X IS DEFEAT`, build a direction-level forbidden movement table, not
  just blocked object cells. The form is `(from_cell, move)`: if `YOU` would
  enter a `DEFEAT` object by moving from a cell in a direction, forbid that edge.
  The same applies to pushing text, because after a successful push `YOU` enters
  the text's previous cell; if that cell overlaps a `DEFEAT` object, that push
  direction must be rejected.
- Dead corners and one-cell pockets are general risks. If key text or objects
  are pushed against a boundary, `STOP`, `DEFEAT`, or a position reachable from
  only one side, they may no longer be pushable from the needed direction later.
  Treat this as a general mechanism to verify before every push, not as
  level-specific coordinate advice.

## Interactive Solving Loop

- A full solution is not needed up front. First read state, then propose one
  small hypothesis that the state can verify.
- When the expectation is clear, reading state after every single step is not
  required. Move until the next meaningful change, such as `left*3` pushing an
  `IS` text away.
- Prefer making the game move. Short action segments are better than heavy
  search for livestream-style play and small-model handoffs.
- Use `check_moves` by default: state the expected rule addition/removal, object
  movement, or completion status first, then let the script judge whether it
  happened.
- To decide whether a cell is walkable, use
  `python3 scripts/read_baba_state.py --at X,Y` to inspect exact occupants and
  properties. Do not infer from `--limit` output plus `grep tile/wall`, because
  truncation may hide a nearby `wall` in the same target cell group.
- If an action may push key objects or text toward a boundary, `STOP`, `DEFEAT`,
  a corner, or a one-cell pocket, shorten the action and verify just before the
  risk point. Do not assume mentally that it can be pushed back out later.
- If unsure whether the `YOU` object is sealed in a compartment that requires
  breaking `STOP` first, run `baba_spatial_diagnostics.py --actor <object>`.
  If it prints `needs_break_first=true`, prioritize testing candidate STOP rule
  breaks/removals before planning a distant WIN.
- In `check_moves` / `baba_action_check.py`, strictly distinguish objects and
  text. `flag` is the flag object; `text_flag` is the word tile that says FLAG.
  Rule-building movement expectations must name `text_*`.
- When an action depends on a lifeline rule, write it as an invariant, such as
  `--expect-rule-kept 'wall is you'` or `--expect-rule-kept 'baba is you'`, so a
  text move does not accidentally lose `YOU`.
- When a bad rule can deadlock a route, use negative constraints such as
  `--forbid-rule-added 'wall is stop'` or `--forbid-rule-present 'flag is stop'`
  instead of only `--expect-moved`.
- For multi-step movement or text pushing, bare `--expect-moved` is a weak check
  and will be rejected by `baba_action_check.py`. Use directional or coordinate
  expectations such as `--expect-moved-delta text_rock:-x` or
  `--expect-position text_rock 1,6`.
- Use `try_moves` only when raw deltas are needed: rule additions/removals,
  target object movement, object disappearance, or completion status changes.
- If temporarily using low-level `scripts/baba_send_keys.py`, add `--observe` by
  default so it delegates to `baba_try.py` and reports the real state delta. Raw
  key sending is only for menus, recovery, or input debugging.
- If a branch goes wrong, use `restart_level` to return to a clean state, then
  shorten or correct the hypothesis.
- Use heavy search only when the problem is mainly moving a small amount of
  text, the target rule is clear, and the search model covers the required
  mechanics.

## Hypothesis Scripts

After reading current state, if the next step is unclear, run:

```bash
python3 scripts/baba_suggest_hypotheses.py --top 8
```

If the question is higher level, namely "which rule should change first?", run:

```bash
python3 scripts/baba_rule_goal_scan.py --top 8
```

`baba_rule_goal_scan.py` does not search exact routes. It outputs the next small
rule delta, such as `+ flag is win`, `- skull is defeat`, or `+ wall is shut`.
It uses current `YOU/WIN/STOP/DEFEAT` rules and approximate reachability to rank
priorities, but the output is not proof. After choosing a candidate, verify that
one delta with either one `--analyze` run or a 1-8 step `action_check`.
`add_rule` candidates can reveal a single-rule `search_next` with
`--show-search`; `remove_rule` candidates should usually be verified with
`baba_action_check.py ... --expect-rule-removed '<rule>'`.

If an existing `WIN` object is temporarily unreachable, `X IS <current YOU noun>`
should also be treated as a high-value stage goal, such as `jelly is baba`. Such
rules may not pass immediately, but they can project control into a target object
or isolated region. Do not skip them just because the next phase is unknown;
verify this single delta with a short action.

This script is not a solver and does not prove routes. It only performs the
first functional filter: from the current live state, identify signals such as
`YOU`, `PUSH`, `OPEN`, `STOP`, and `DEFEAT`, then produce a few high-value
templates, for example:

- `blocker IS SHUT` + `movable tool IS OPEN`
- `current controllable object IS WIN`
- `some object IS YOU`
- break a visible `X IS STOP`

The `search_next` command is only a candidate route-generation entry point, not
a fact. Every candidate still must enter the short feedback loop and be verified
with `check_moves` / `scripts/baba_action_check.py`.

By default, `search_next` commands are hidden. Only add `--show-search` to
`baba_suggest_hypotheses.py` after choosing exactly one candidate and preparing
for the single route-analysis attempt.

After `baba_suggest_hypotheses.py` output, run at most one `--analyze` for one
candidate. Then immediately choose a 1-8 step `check_moves` /
`scripts/baba_action_check.py` action segment with explicit `--expect-*`.
Do not continue with more than five lines of rule-arrangement reasoning.

If the next step involves pushing text or building/breaking a rule, shrink the
action segment to 1-3 steps. Do not plan the full text route before confirming
the first push works.

When calling `baba_search_route.py`, `--make-rule` / `--make-prefix` must mean
the next minimal rule target, not the whole level's final target. If completion
requires multiple rule changes, search and verify one rule delta at a time: for
example, first break `wall is stop`; after that is verified, consider
`flag is win`. Do not make the first search aim directly at the final
`flag is win`.

If the live state's `turn > 0`, `search_next` includes `--from-live-state`.
Do not remove it, because otherwise `baba_search_route.py` searches from the
initial `.l` layout instead of the current board after pushes.

In `baba_search_route.py --analyze`, `selected_text` entries such as
`text_flag#0:flag@(x,y)` mean the FLAG word tile, not the `flag` object.
Movement checks must still use `flag` versus `text_flag` according to
`baba_action_check.py`.

`edge_text_warnings` are hard facts: do not plan vertical pushes for top/bottom
edge text marked `vertical_locked`; do not plan horizontal pushes for left/right
edge text marked `horizontal_locked`; corner text marked `corner_locked` is
usually not a movable resource.

`read_baba_state.py` also prints `edge_text_warnings` near the top. If state
reading already says a text is locked on an axis, choose another target or prove
the specific push with a 1-8 step `baba_action_check.py`; do not continue prose
reasoning about that blocked rule arrangement.

If `X IS WIN` already exists and the map is separated by a hazard rule such as
`Y IS DEFEAT`, `Y IS SINK`, `Y IS HOT`, or `Y IS MELT`, first test "break the
hazard rule, then touch the existing WIN object." Do not jump straight to
rearranging `WIN` text. `read_baba_state.py`'s `hazard_break_opportunities` and
`baba_suggest_hypotheses.py`'s `break rule: remove ...` are hard hints.

Typical usage:

```bash
python3 scripts/baba_suggest_hypotheses.py --top 5
python3 scripts/baba_suggest_hypotheses.py --json --top 5
python3 scripts/baba_search_route.py --from-live-state --make-rule "flag is win" --select-text flag --select-text win --all-is --no-touch-win --analyze
```

If the first script candidate is something like `wall is shut + star is open`,
the next step is not to enumerate all text arrangements. Verify whether each
target rule can be built with a short route, then verify whether the object
interaction really opens the path.

When `blocker IS SHUT` + `pushable tool IS OPEN` is already true or has become a
top candidate, first use the real-blocker ranking script to filter out walls
that do not actually gate progress:

```bash
python3 scripts/baba_rank_breakout_targets.py --subject wall --top 8
python3 scripts/baba_rank_breakout_targets.py --subject wall --top 3 --json
python3 scripts/baba_rank_breakout_targets.py --subject wall --top 8 --setup-search --setup-candidates 8
```

This script computes from live state:

- Direction-level forbidden movement edges around `DEFEAT`, such as
  `(12,11)->up`.
- How many new cells become reachable after deleting each candidate `STOP`
  object.
- Whether the object is a real gate: which side is reachable before deletion,
  and which side becomes newly reachable afterward.
- Collision slots for `OPEN+PUSH` tools: tool target cell, Baba standing cell,
  and push direction.

`--setup-search` continues with a small object-push search on the filtered
results. It tries to push the `OPEN+PUSH` tool and necessary `SHUT` text into
the "just before hitting the wall" state and prints `setup_route`. This is
slower but more reliable as a second filter. Do not default to whole-map
enumeration; prefer limiting `--setup-candidates`.

The ranking result only chooses which wall/door to hit first. It does not
replace real verification. After choosing a target, still use `check_moves` /
`scripts/baba_action_check.py` to verify that the tool and blocker are both
removed, then read state to confirm reachability or completion changes.

## Solving Efficiency Protocol

Some models interpret "first principles" and "MECE" as "prove the full solution
mentally first." Do not do that in this project. Unless the user explicitly asks
for a reasoning explanation, each solving round should output and execute only
one short feedback loop:

```text
Observation: the current 1-3 key facts.
Hypothesis: what this short action segment is expected to change.
Action: one check_moves/map_route/restart_level command; normal level actions should usually be 1-8 steps.
Result: read only the delta; decide whether to continue, shorten, undo, or restart.
```

- Each round may choose only one observable goal:
  - Change one rule.
  - Move one key text or object.
  - Approach a target region.
  - Verify whether a blocker exists.
- Write at most five lines to the user per round:
  `Observation` / `Hypothesis` / `Action` / `Result` / `Next`.
  If more than five lines are needed, the action is too large and must be
  shortened.
- Do not verify routes in thinking tokens. Verification must be delegated to
  `check_moves` / `scripts/baba_action_check.py`, and the command must include
  explicit `--expect-*`.
- After `baba_suggest_hypotheses.py` or one `baba_search_route.py --analyze`
  output, the next step must be a 1-8 step `check_moves` /
  `baba_action_check.py` verification segment. Do not continue with more than
  five lines of text/rule arrangement reasoning.
- The tool layer has a hard `baba_loop_guard.json` constraint: after a normal
  `read_state`, the only allowed next analysis is `rule_goal_scan` /
  `suggest_hypotheses`, or an `action_check`; after a rule goal/hypothesis,
  only one `baba_search_route.py --analyze` or `action_check` is allowed; after
  `--analyze`, only `action_check` is allowed. If the script prints
  `loop_guard=action_required`, do not explain. Immediately follow
  `allowed_next` with a short action segment.
- Search targets must be small. Do not ask search "how to pass" or "how to make
  the final WIN rule" if intermediate rule changes are still needed. Ask only
  "what next rule/prefix should be added, removed, or kept," execute and verify,
  then ask again.
- Verifying only "something moved" is insufficient. For multi-step approach,
  text pushes, or key object pushes, the action segment must include a checkable
  direction or endpoint, such as `--expect-moved-delta text_is:+x` or
  `--expect-position baba 7,4`. Otherwise shorten the action to a single-step
  debug segment.
- If the target is building `X IS WIN` and `X IS YOU` is already active, the
  action segment must also include `--expect-rule-kept 'X is you'`. If the move
  may pass near `STOP` / `YOU` / `WIN` text, also add `--expect-rule-kept` or
  `--forbid-rule-added` constraints for key rules.
- After entering a new level, if there is no active benchmark, the only next
  step is `start_benchmark`, not level analysis.
- Do not manually simulate more than eight steps before execution. Split longer
  plans into two verifiable action segments.
- Do not enumerate all possible rule layouts, coordinate routes, or "maybe"
  branches. Use MECE to separate the main types, then try the cheapest and most
  observable one first.
- If more than one action segment is already planned, write the plan into the
  current run directory's `baba_route_plan.md`, but keep only 1-3 pending short
  segments. Each segment must include action, expected delta, state anchor, and
  status (`planned`, `pass`, `fail`, or `invalid`).
- `check_moves` / `baba_action_check.py` automatically appends the short action,
  expected delta, and observed result to `baba_route_plan.md`. This is a
  scratchpad, not a solution source.
- After `check_moves` / `baba_action_check.py` returns `check=fail`, the default
  next step is `python3 scripts/read_baba_state.py --limit 60` to confirm the
  real board.
- Do not treat `expanded_move_count` as a safe undo count. Failed segments may
  contain wall bumps or invalid input; `z*N` can undo earlier successful text
  pushes or rule changes.
- If the script prints `undo_expanded_steps_unsafe=true` or
  `preserved_progress=...`, do not undo the whole segment and do not restart.
  Read state and continue from the real current delta, or if rollback is truly
  needed, use `python3 scripts/baba_undo.py --steps 1` one step at a time and
  observe.
- After `check=fail`, all unexecuted segments in `baba_route_plan.md` are
  invalid. Do not continue explaining what "should have moved"; do not plan from
  pre-failure mental coordinates; do not immediately run another long action
  segment; do not use `baba_action_check.py 'z'` instead of `baba_undo.py`; do
  not restart while key progress is preserved.
- If `baba_restart.py` prints `restart_guard=preserved_progress`, a recent
  `action_check` has passed. Do not restart unless the user explicitly asks or
  you manually add `--force`.
- `baba_action_check.py` rejects contradictory expectations, such as the same
  rule being both `--expect-rule-added` and `--expect-rule-removed`.
- Use `--expect-completion-status 3` only when `X IS WIN` already exists, or
  when this segment explicitly expects `--expect-rule-added 'X is win'`.
- If an unfinished active benchmark already exists, switching to a new level
  requires explicit `--force-new`, and the script's abandonment warning must be
  treated as a risk. Do not treat it as normal navigation.
- If two consecutive action segments produce no rule change, key object
  movement, positional improvement, or completion-status change, stop mental
  patching and first `restart_level` or return to the last clean checkpoint.
- If the same sentence contains "let me think", "让我再想", "this is complex",
  "这很复杂", or "getting complicated" for the second time, immediately rewrite
  the problem as a shorter verifiable action instead of continuing to simulate.
- After reading `baba_action_check.py` / `baba_try.py` output, treat the script
  output as the source of truth. Do not restate the full coordinate simulation;
  the next round should explain only differences directly related to the delta.
- Reusable mechanisms may be recorded, but do not write record files as full
  inner monologues or level-solution spoilers.
- Agent startup prompts should require concise reporting in the user's language
  without showing long reasoning. Do not write prompts such as "think in
  Chinese" that encourage long inner reasoning.
- TTS is only for short action/result reports. `agent_tts.py` rejects long
  planning narration by default. Do not use TTS to speak "let me think",
  "maybe", or complex planning narration.

## Record Requirements

The current run directory comes from `current_run_id` in `baba_config.json`. Its
path looks like:

```text
runs/<number_agent_model>/
```

Examples: `runs/001_agent_model/` or `runs/002_claude_sonnet/`. Do not write to
a fixed `default_run_id`.

After every solved level, update all four files in the current run directory:

- `baba_benchmark_log.md`: mechanical benchmark facts, score steps, evidence.
- `baba_level_notes.md`: level route, key checkpoints, coordinates, and results.
- `baba_learned_rules.md`: reusable lessons; if there are no new lessons, say so.
- `baba_growth_diary.md`: first-person learning/growth diary in the user's
  language; do not write it as a route log.

The current run directory's `baba_route_plan.md` is a temporary route-plan
scratchpad used to constrain pre-action short hypotheses and post-action deltas.
It does not replace the four formal record files and must not be used as a
benchmark solution source.

Score field conventions:

- `score_steps` is the primary ranking field. Lower is better.
- Prefer the live state's `turn` at the moment of winning as `score_steps`, with
  source `live_state_turn`.
- If live-state `turn` is unavailable, fall back to verified route expanded step
  count, with source `expanded_route_steps`.
- If the final `baba_action_check.py` output contains
  `observed_completion_status=<level>=3` and `observed_after_turn=<N>`, pass
  `--game-turns <N>` to `baba_benchmark.py --record-pass` when recording, so the
  win turn is not lost after the game returns to the map.
- If the level was passed through multiple interactive `action_check` segments,
  use
  `python3 scripts/baba_benchmark.py --record-pass --from-route-plan --game-turns <N> --note '<summary>'`
  to extract the route from the current run's `baba_route_plan.md`. Add
  `--passed-only` only after confirming failed segments were undone or should
  not count in replay.
- In real testing, undo returns the board state but does not roll back the live
  state's `turn`; undo itself does not add an extra turn.
- `elapsed_seconds` is only diagnostic metadata for infrastructure differences.
  It is not an ability score.

Root `runs/*.template.md` files are public templates. Real run subdirectories
are not submitted by default.

## Known Routes Boundary

- `runs/<run_id>/baba_known_routes.json` is independent replay data, not a
  benchmark solution source.
- `play_known_route` may be used to replay or verify old routes, but benchmark
  mode must record the process of learning, trying, and passing from the current
  state.
- `record_pass` writes `last_score_steps` / `best_score_steps` back to that JSON
  so later replay can see step scores. This does not change the benchmark rule
  that known routes are forbidden as a solution source.

## Installation And Configuration Boundary

Installation, configuration, MCP server configuration, and tool inventory belong
in `README.md`. This file only defines the goals, behavior, risk boundaries, and
record requirements after an agent takes over.
