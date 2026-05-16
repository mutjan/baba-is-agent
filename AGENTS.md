# Baba Agent Contract

本项目的目标不是复现已有路线，而是让 agent 从当前真实状态出发，交互式学习并通关 Baba Is You 关卡，同时留下可验证的 benchmark 记录。

## 目标与成功标准

- 每次接手先确认真实状态：配置、当前 save、当前关卡、初始规则、是否在地图。
- Benchmark 是从零开始的学习和通关能力测试，不要把当前 run 目录里的 `baba_known_routes.json` 当成解法来源。
- 通关证据只有一个硬标准：对应关卡 save completion status 变成 `3`。
- Benchmark 主评分是通关步数 `score_steps`，不是墙钟时间；墙钟用时只作辅助元数据。
- 每过一关，记录本关 `score_steps` 并更新当前 run 目录里的记录文件。
- 回答用户时使用用户的语言；本仓库协作默认每次回答以“根据第一性原理……”开头。

## 协作输出规则

- 先确认真实目标、约束和成功标准，不要套用惯例。
- 如果目标、成功标准或风险边界不清晰且会影响实现方向，先向用户提问。
- 如果目标清晰但当前路径不是最简单、低风险、可验证的方案，直接指出更好的替代方案。
- 需要决策时按 MECE 原则覆盖主要可能性。
- 默认简洁输出：结论、关键理由、改动点、验证结果。
- 第一性原理在本项目里等于寻找最短可验证反馈回路，不等于穷举所有路线或长篇证明。

## 首选入口

新 clone 或新 agent 接手后，从根目录运行：

```bash
python3 start_benchmark.py --run-id 001_agent_model
```

如果 MCP 可用，优先通过 MCP 调用 `start_benchmark`，不要优先直接调用裸脚本。裸脚本是 fallback 和调试入口。

干跑检查：

```bash
python3 start_benchmark.py --dry-run --skip-primer --no-inspect
```

## MCP 优先流程

MCP 工具可用时，默认按这个顺序工作：

1. `app_status`，确认游戏进程和状态文件是否可读
2. `suggest_next_action`，不确定下一步时先调用它
3. `inspect_state`
4. `rule_goal_scan`，当问题是“不知道先改哪条规则”时先扫下一条最小规则 delta
5. `set_current_run_id`，仅当当前 run id 不对或为空
6. `start_benchmark`
7. `check_moves`，先声明一个预期 delta，再用脚本验证短行动段
8. `try_moves`，仅在调试原始 delta 或没有明确预期时使用
9. `restart_level`，当实验把局面弄坏或需要回到干净检查点
10. `undo_moves`，当上一段 `check_moves` 失败且要回到失败段之前
11. `return_to_map`，当需要从关卡或下级地图回到上级地图
12. `navigate_next`，当当前状态是世界地图或 overworld
13. `record_pass`，仅当完成态已经是 `3`

只在 MCP 不可用或正在调试 MCP wrapper 时回退到 `python3 scripts/...`，并说明原因。
MCP 工具名不是脚本名；不要按工具名猜脚本文件。特别是 `navigate_next`
只存在于 MCP，脚本 fallback 是 `python3 scripts/baba_map_route.py --execute`。
本项目没有 `scripts/baba_navigate_next.py`。

## 游戏进程识别

- macOS 上配置里的 app/bundle 名通常是 `Baba Is You`，但实际前台进程可能是引擎名 `Chowdren`。
- 不要把 `System Events` 里的 `processes contains "Baba Is You"` 当作唯一运行判断；它可能是假阴性。
- 用 MCP `app_status` 或脚本 `python3 scripts/baba_app_status.py` 判断。`running_process_detected=True` 且 `running_process_name=Chowdren` 是正常状态。
- `frontmost_process=Chowdren` 只能说明窗口聚焦；能否读状态、能否移动，还要看 `runtime_state_available`、`inspect_state` 和后续 `check_moves` 结果。

## 地图与普通关卡的区分

- 如果当前关卡是世界地图或 overworld，例如 `106level`、`177level`，不要按普通 Baba 关卡求解。
- 地图上没有 Baba 对象不是错误。地图的可控对象是 live-state 里的 `cursor`，控制模型是 `cursor is select`。
- 地图状态下优先使用 MCP `navigate_next` 进入未完成关卡；脚本 fallback 固定为 `python3 scripts/baba_map_route.py --execute`。
- `navigate_next` / `baba_map_route.py --execute` 只负责进关，不等于开始计分。进入普通关卡后，先运行 MCP `start_benchmark` 或 `python3 start_benchmark.py`，再开始解题。
- 不要自己从所有可见 `level` 单元里猜目标。地图上会显示很多当前不可达的关卡；以 `suggest_next_action` 的 `route_target` / `route_moves` 或 `map_route` 输出为准。
- 大地图通过 `0level` 后，典型下一关是 `1level`，坐标 `(11,14)`；从 `0level` 坐标 `(10,16)` 的路线是 `right,up,up,enter`。
- 在关卡内或下级地图内需要返回上级地图时，用 `return_to_map`。底层按键是 `esc,down,enter`。

不要在地图或下级地图上开始关卡 benchmark。`start_benchmark` 如果检测到当前是地图，会提示先 `navigate_next`，避免把地图当普通关卡计分。

如果 `start_benchmark` 报 `active_state_mismatch=true`，说明当前 live level 和未完成的 active benchmark 文件不一致。此时不要继续解题，也不要用 `--record-pass --level ...` 绕过；按脚本给出的 `--force-new` 修正 active 记录后再行动。

## Baba 基础规则提示

- 规则通常由可见文字组成，形式是 `NOUN IS PROPERTY`。
- `YOU` 标记可控制对象；`WIN` 标记胜利对象；`STOP` 阻挡移动；`DEFEAT` 会消灭 `YOU`。
- `SHUT` 和 `OPEN` 接触时会互相移除，例如钥匙开门。
- 文字默认可推动。`TEXT IS PUSH` 是基础规则，可能生效但不会在关卡里显式摆出来。
- `PUSH` 的含义是：`YOU` 对象朝某方向移动时，可以把对应物体或文字向前推一格，前提是整条被推动链背后有空位。
- 如果推动链背后是 `STOP`、地图边界或不可推动阻挡物，推动不会发生。
- 每次推 `PUSH` 物或文字前都要显式检查链式推动：链上每个物体/文字都会前进一格，链尾后方必须是空位；不要只看被接触的第一格。
- 判断边界、角落、封闭空间时优先用 `python3 scripts/baba_spatial_diagnostics.py --actor baba`。角落里的可推动单位几何上没有可推动方向；边缘上的可推动单位通常只能沿边缘轴向推动。`--actor` 默认是 `baba`，可以传 `--actor wall` 等对象名。
- 推动文字可以创建或打断规则；移动 `IS`、`YOU`、`WIN`、`STOP`、`PUSH`、`OPEN`、`SHUT` 或名词文字通常是解题核心。
- 围绕 `X IS DEFEAT` 的对象要生成方向级禁止移动表，而不只是把对象格当成普通阻挡。形式是 `(from_cell, move)`：如果 `YOU` 从某格朝某方向会进入 `DEFEAT` 对象所在格，就禁止这条边。推文字时同理，因为成功推动后 `YOU` 会进入被推文字原来的格子；如果该原格叠着 `DEFEAT` 对象，这个方向的推动也必须排除。
- 死角和单格口袋是通用风险：如果关键文字或物体被推到边界、`STOP`、`DEFEAT` 或只能从一侧接触的位置，之后可能无法从需要的方向再推动。不要写成本关坐标提示；只把它当成每次推动前要用状态验证的通用机制。

## 交互式解题循环

- 不需要先知道完整解法。先读状态，提出一个能被状态验证的小假设。
- 有明确预期时，不必一步一读；可以走到下一个有意义变化为止，例如 `left*3` 推开某个 `IS`。
- 优先让游戏动起来：短行动段比重计算搜索更适合直播和小模型接手。
- 默认使用 `check_moves`：先说清楚预期是新增/打断哪条规则、移动哪个对象，或拿到完成态，再让脚本判定是否命中。
- 判断某一格是否可走时，用 `python3 scripts/read_baba_state.py --at X,Y` 查目标格精确 occupants 和属性；不要用 `--limit` 后再 `grep tile/wall` 推断，因为分组截断可能隐藏同一目标格附近的 `wall`。
- 如果动作会把关键物体或文字推向边界、`STOP`、`DEFEAT`、墙角或单格口袋，必须把动作缩短到进入风险前一格先验证；不要在脑内假设之后还能从另一侧推出。
- 如果不确定 `YOU` 对象是否被围在一个需要先打破 `STOP` 的封闭区域里，先运行 `baba_spatial_diagnostics.py --actor <object>`；如果输出 `needs_break_first=true`，下一步优先测试打断/移除候选 STOP 规则或对象，而不是规划远处 WIN。
- `check_moves` / `baba_action_check.py` 里必须严格区分实体和文字：`flag` 是旗子实体，`text_flag` 才是写着 FLAG 的文字块；构造规则时预期移动对象必须写 `text_*`。
- 当行动依赖某条生命线规则时，把它写成不变量：例如保持控制权用 `--expect-rule-kept 'wall is you'` / `--expect-rule-kept 'baba is you'`，避免为了移动文字而顺手失去 `YOU`。
- 当某条坏规则会卡死路线时，用 `--forbid-rule-added 'wall is stop'`、`--forbid-rule-present 'flag is stop'` 等负约束，而不是只写 `--expect-moved`。
- 多步移动或推动文字时，裸 `--expect-moved` 属于弱验证，会被 `baba_action_check.py` 拒绝；改用 `--expect-moved-delta text_rock:-x` 或 `--expect-position text_rock 1,6` 这类方向/坐标预期。
- 只在需要看完整原始 delta 时使用 `try_moves`：规则新增/消失、目标对象移动、对象消失、完成态变化。
- 如果临时使用低层 `scripts/baba_send_keys.py`，默认加 `--observe`，让它转交给 `baba_try.py` 并输出真实状态 delta；裸发按键只用于菜单、恢复或调试输入本身。
- 如果分支错了，用 `restart_level` 回到干净状态，再缩短或修正假设。
- 只有当问题主要是移动少量文字、目标规则明确、且搜索模型覆盖这些机制时，才使用重搜索。

## 假设生成脚本

当读完当前状态但还不知道下一步该试什么时，先运行：

```bash
python3 scripts/baba_suggest_hypotheses.py --top 8
```

如果问题更上层，是“不知道先改变哪条规则”，先运行：

```bash
python3 scripts/baba_rule_goal_scan.py --top 8
```

`baba_rule_goal_scan.py` 不搜索具体走法，只输出下一条最小规则 delta，例如 `+ flag is win`、`- skull is defeat`、`+ wall is shut`。它会用当前 `YOU/WIN/STOP/DEFEAT` 等规则和近似可达区判断优先级，但输出不是证明；选中一个候选后仍然只能对这一条 delta 做一次 `--analyze` 或一个 1-8 步 `action_check`。`add_rule` 候选可用 `--show-search` 显示单规则 `search_next`；`remove_rule` 候选优先用 `baba_action_check.py ... --expect-rule-removed '<rule>'` 验证。
如果某个已有 `WIN` 对象暂时不可达，`X IS <当前YOU名词>` 也应被当成高价值阶段目标，例如 `jelly is baba`。这类规则不一定立刻通关，但能把控制权投射到目标对象/隔离区域；不要因为“不知道下一步怎么办”而跳过，先用短动作验证这个单一 delta。

这个脚本不是求解器，也不负责证明路线。它只做第一层功能筛选：从当前 live state 里识别 `YOU`、`PUSH`、`OPEN`、`STOP`、`DEFEAT` 等信号，按少数高价值模板生成候选假设，例如：

- `阻挡物 IS SHUT` + `可移动工具 IS OPEN`
- `当前可控对象 IS WIN`
- `某个对象 IS YOU`
- 打断可见的 `X IS STOP`

脚本输出的 `search_next` 只能作为候选路线生成入口，不能直接当事实。每个候选仍必须进入短反馈循环，用 `check_moves` / `scripts/baba_action_check.py` 验证真实 delta。
默认不会显示 `search_next` 命令；只有已经选定一个候选并准备做唯一一次路线分析时，才给 `baba_suggest_hypotheses.py` 加 `--show-search`。
`baba_suggest_hypotheses.py` 输出后，最多只允许对一个候选运行 1 次 `--analyze`；随后必须立刻选择一个 1-8 步的 `check_moves` / `scripts/baba_action_check.py` 动作段，并带明确 `--expect-*`。禁止继续写超过 5 行的规则排列推演。
如果下一步涉及推动文字或构造/打断规则，动作段优先缩到 1-3 步；不要在确认第一格推动是否成立前继续推演完整文字路线。
调用 `baba_search_route.py` 时，`--make-rule` / `--make-prefix` 只能表示“下一步最小规则目标”，不是整关最终目标。如果通关需要多次改规则，就每次只搜索/验证一个规则 delta：例如先打断 `wall is stop`，验证通过后再考虑 `flag is win`，而不是第一次搜索就瞄准最终 `flag is win`。
如果 live state 的 `turn > 0`，`search_next` 会带 `--from-live-state`；不要去掉它，否则 `baba_search_route.py` 会从初始 `.l` 关卡布局搜索，和当前已经推动过的局面不一致。
`baba_search_route.py --analyze` 的 `selected_text` 输出里 `text_flag#0:flag@(x,y)` 表示 FLAG 文字块，不是物体 `flag`。物体和文字的移动仍以 `baba_action_check.py` 的 `flag` / `text_flag` 区分为准。
`edge_text_warnings` 是硬事实：`vertical_locked` 的顶/底边文字不要计划上下推动，`horizontal_locked` 的左右边文字不要计划左右推动，`corner_locked` 的角落文字通常不能作为可移动资源。
`read_baba_state.py` 也会在输出顶部显示 `edge_text_warnings`；如果状态读取已经说明某个文字轴向锁死，下一步必须换目标或用 1-8 步 `baba_action_check.py` 证明具体推动，而不是继续写规则排列推演。
如果已经有 `X IS WIN`，同时地图被 `Y IS DEFEAT` / `Y IS SINK` / `Y IS HOT` / `Y IS MELT` 这类 hazard 规则隔开，优先测试“打断 hazard 规则后去碰现有 WIN”，不要直接跳到重排 `WIN` 文字。`read_baba_state.py` 的 `hazard_break_opportunities` 和 `baba_suggest_hypotheses.py` 的 `break rule: remove ...` 是硬提示。

典型用法：

```bash
python3 scripts/baba_suggest_hypotheses.py --top 5
python3 scripts/baba_suggest_hypotheses.py --json --top 5
python3 scripts/baba_search_route.py --from-live-state --make-rule "flag is win" --select-text flag --select-text win --all-is --no-touch-win --analyze
```

如果脚本给出的第一候选是类似 `wall is shut + star is open`，下一步不是穷举所有文字排列，而是分别验证这些目标规则是否能被短路线构造；构造成功后再验证实体交互是否真的打开通路。

当 `阻挡物 IS SHUT` + `可推动工具 IS OPEN` 已经成立，或已经被列为最高候选时，先用真挡路墙排序器筛掉“不挡路墙”：

```bash
python3 scripts/baba_rank_breakout_targets.py --subject wall --top 8
python3 scripts/baba_rank_breakout_targets.py --subject wall --top 3 --json
python3 scripts/baba_rank_breakout_targets.py --subject wall --top 8 --setup-search --setup-candidates 8
```

这个脚本从 live state 计算：

- `DEFEAT` 周围的方向级禁止移动边，例如 `(12,11)->up`。
- 假设删除每个候选 `STOP` 对象后，`YOU` 可达区域新增多少格。
- 这个对象是否是真门槛：删除前哪一侧可达，删除后哪一侧变成新区域。
- `OPEN+PUSH` 工具的撞击槽位：工具目标格、Baba 站位、推动方向。

`--setup-search` 会在初筛结果上继续做小型推物搜索，尝试把 `OPEN+PUSH` 工具和必要的 `SHUT` 文字推到“撞墙前一刻”的局面，并输出 `setup_route`。这是慢一点但更可靠的二筛；不要默认全图穷举，优先限制 `--setup-candidates`。

排序结果只能决定“优先撞哪一格墙/门”，不能替代真实验证。选中候选后仍要用 `check_moves` / `scripts/baba_action_check.py` 验证工具和阻挡物是否真的一起消失，再读状态确认可达区域或完成态变化。

## 解题效率协议

有些模型会把 `第一性原理` 和 `MECE` 理解成“先在脑内证明完整解法”。本项目不要这样做。除非用户明确要求讲解推理过程，否则每轮解题只输出并执行一个短反馈循环：

```text
观察：当前最关键的 1-3 个事实。
假设：这段短动作预期会改变什么。
动作：check_moves/map_route/restart_level 的一个命令，普通关卡动作段优先控制在 1-8 步。
结果：只读 delta，决定继续、缩短、撤回或重启。
```

- 每轮只能选择一个可观测目标：
  - 改变一条规则。
  - 移动一个关键文字或物体。
  - 接近一个目标区域。
  - 验证一个阻挡是否成立。
- 每轮对用户最多写 5 行：`观察` / `假设` / `动作` / `结果` / `下一步`。如果需要解释超过 5 行，说明动作太大，必须缩短。
- 不要在 thinking token 里验证路线。验证必须交给 `check_moves` / `scripts/baba_action_check.py`，并且命令里要有 `--expect-*` 预期。
- `baba_suggest_hypotheses.py` 或一次 `baba_search_route.py --analyze` 输出后，下一步必须是一个 1-8 步 `check_moves` / `baba_action_check.py` 验证段；不要继续展开超过 5 行的文字/规则排列推演。
- 工具层有 `baba_loop_guard.json` 硬约束：普通 `read_state` 后只能 `rule_goal_scan` / `suggest_hypotheses` 或 `action_check`；规则目标/假设输出后只能 1 次 `baba_search_route.py --analyze` 或 `action_check`；`--analyze` 后只能 `action_check`。如果脚本输出 `loop_guard=action_required`，不要解释，立刻照 `allowed_next` 做短动作段。
- 搜索目标必须拆小：不要问搜索“怎样通关”或“怎样形成最终 WIN 规则”如果中间还要改别的规则；只问“下一条我要新增/打断/保持的规则或前缀是什么”，执行并验证后再问下一次。
- 只验证“某物移动了”不够。多步接近、推文字、推关键物体时，动作段必须包含可检查的方向或终点，例如 `--expect-moved-delta text_is:+x`、`--expect-position baba 7,4`；否则先把动作缩短到单步调试。
- 如果目标是构造 `X IS WIN` 且当前 `X IS YOU` 已经成立，动作段必须同时带 `--expect-rule-kept 'X is you'`；如果动作可能经过 `STOP`/`YOU`/`WIN` 文本附近，也要为关键规则添加 `--expect-rule-kept` 或 `--forbid-rule-added`。
- 进入新关后没有 active benchmark 时，唯一下一步是 `start_benchmark`，不是分析关卡。
- 不要在执行前手工推演超过 8 步；超过就拆成两个可验证动作段。
- 不要枚举所有可能规则排列、所有坐标路线、所有 “maybe” 分支。按 MECE 分清主要类型后，选择最便宜、最可观测的一类先试。
- 如果已经计划好不止一个动作段，把计划写入当前 run 目录的 `baba_route_plan.md`，但只允许保留 1-3 个待验证短段；每段必须包含动作、预期 delta、状态锚点和状态（planned/pass/fail/invalid）。
- `check_moves` / `baba_action_check.py` 会把本次短动作、预期 delta 和实测结果自动追加到 `baba_route_plan.md`。这只是 scratchpad，不是解法来源。
- `check_moves` / `baba_action_check.py` 返回 `check=fail` 后，第一下一步默认是 `python3 scripts/read_baba_state.py --limit 60`，先确认真实局面。
- 不要把 `expanded_move_count` 当成安全 undo 次数。失败段可能包含撞墙/无效输入，`z*N` 会越过失败段，撤销更早的成功推字或规则变化。
- 如果脚本输出 `undo_expanded_steps_unsafe=true` 或 `preserved_progress=...`，禁止整段 undo，也不要 restart；只能读状态后从当前真实 delta 继续，或在确实要回退时用 `python3 scripts/baba_undo.py --steps 1` 单步撤回并观察。
- `check=fail` 后 `baba_route_plan.md` 里所有未执行段都视为失效；禁止继续解释“理论上应该移动了什么”，禁止从失败前的脑内坐标继续规划，禁止立刻再跑另一个长动作段，禁止用 `baba_action_check.py 'z'` 代替 `baba_undo.py`，禁止在关键进展仍保留时重启。
- 如果 `baba_restart.py` 输出 `restart_guard=preserved_progress`，说明最近一次 `action_check` 已经通过；禁止重启，除非用户明确要求或手动加 `--force`。
- `baba_action_check.py` 会拒绝矛盾预期，例如同一条规则同时 `--expect-rule-added` 和 `--expect-rule-removed`。
- 只有当前已存在 `X IS WIN`，或本段明确 `--expect-rule-added 'X is win'`，才能使用 `--expect-completion-status 3`。
- 如果已有未完成 active benchmark，切到新关只能显式 `--force-new`，并必须把脚本打印的 abandonment warning 当成风险；不要把它当正常导航。
- 如果连续两段动作没有带来规则变化、关键对象移动、位置改善或完成态变化，停止脑内补救，先 `restart_level` 或回到上一个干净检查点。
- 如果一句话里第二次出现 “let me think / 让我再想 / 这很复杂 / getting complicated”，立刻把问题改写成一个更短的可验证动作，而不是继续推演。
- 读完 `baba_action_check.py` / `baba_try.py` 的结果后，以脚本输出为事实来源，不再复述完整坐标模拟；下一轮只解释和 delta 直接相关的差异。
- 可以记录学到的通用机制，但不要把记录文件写成完整内心独白或关卡解法剧透。
- 给 agent 的启动提示应要求“用用户语言简洁汇报，不展示长思考过程”。不要写“用中文思考”这类会鼓励长篇内心推演的提示。
- TTS 只用于短动作/结果汇报。`agent_tts.py` 默认会拒绝长规划旁白；不要用 TTS 播“让我想/也许/计划很复杂”这类推理。

## 记录要求

当前 run 目录来自 `baba_config.json` 的 `current_run_id`，路径形如：

```text
runs/<number_agent_model>/
```

例如 `runs/001_agent_model/` 或 `runs/002_claude_sonnet/`。不要写入固定的 `default_run_id`。

每过一关，当前 run 目录里的四个文件都要更新：

- `baba_benchmark_log.md`：机械 benchmark 事实、评分步数、证据。
- `baba_level_notes.md`：关卡路线、关键检查点、坐标和结果。
- `baba_learned_rules.md`：可复用经验；没有新经验时写明没有。
- `baba_growth_diary.md`：第一人称学习成长日记，使用用户的语言，不要写成路线日志。

当前 run 目录里的 `baba_route_plan.md` 是临时路线计划 scratchpad，用来约束行动前的短假设和行动后的 delta 结果；它不替代上面四个正式记录文件，也不能作为 benchmark 解法来源。

评分字段约定：

- `score_steps` 是主排序字段，越小越好。
- 优先用本关刚刚 win 时 live state 的 `turn` 作为 `score_steps`，来源记为 `live_state_turn`。
- 如果 live state 的 `turn` 不可用，回退到验证路线展开步数，来源记为 `expanded_route_steps`。
- 如果最终 `baba_action_check.py` 输出 `observed_completion_status=<level>=3` 且有 `observed_after_turn=<N>`，记录通关时把 `--game-turns <N>` 传给 `baba_benchmark.py --record-pass`，避免通关后跳回地图导致脚本读不到刚才关卡的 win turn。
- 如果本关是交互式多段 `action_check` 过关，可以用 `python3 scripts/baba_benchmark.py --record-pass --from-route-plan --game-turns <N> --note '<summary>'` 从当前 run 的 `baba_route_plan.md` 抽取路线；只有确认失败段都已撤销或不应计入 replay 时，才额外加 `--passed-only`。
- 实测 undo 会把局面撤回，但不会把 live state `turn` 撤回；undo 本身不额外加一回合。
- `elapsed_seconds` 只保留作排查基础设施差异的参考，不作为能力评分。

根目录 `runs/*.template.md` 是公开模板。真实 run 子目录默认不提交。

## Known Routes 边界

- `runs/<run_id>/baba_known_routes.json` 是独立 replay 数据，不是 benchmark 解题来源。
- `play_known_route` 可以用于回放或校验旧路线，但 benchmark 模式必须记录从当前状态学习、尝试、通过的过程。
- `record_pass` 会把 `last_score_steps` / `best_score_steps` 写回该 JSON，方便之后回放时看到步数成绩；这不改变 benchmark 禁止读路线解题的边界。

## 安装与配置边界

安装、配置、MCP server 配置、工具清单放在 `README.md`。本文件只规定 agent 接手后的目标、行为、风险边界和记录要求。
