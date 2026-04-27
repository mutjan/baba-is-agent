# Baba Agent Contract

根据第一性原理，本项目的目标不是复现已有路线，而是让 agent 从当前真实状态出发，交互式学习并通关 Baba Is You 关卡，同时留下可验证的 benchmark 记录。

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
4. `set_current_run_id`，仅当当前 run id 不对或为空
5. `start_benchmark`
6. `try_moves`，用最短的有意义行动段测试假设
7. `restart_level`，当实验把局面弄坏或需要回到干净检查点
8. `return_to_map`，当需要从关卡或下级地图回到上级地图
9. `navigate_next`，当当前状态是世界地图或 overworld
10. `record_pass`，仅当完成态已经是 `3`

只在 MCP 不可用或正在调试 MCP wrapper 时回退到 `python3 scripts/...`，并说明原因。

## 游戏进程识别

- macOS 上配置里的 app/bundle 名通常是 `Baba Is You`，但实际前台进程可能是引擎名 `Chowdren`。
- 不要把 `System Events` 里的 `processes contains "Baba Is You"` 当作唯一运行判断；它可能是假阴性。
- 用 MCP `app_status` 或脚本 `python3 scripts/baba_app_status.py` 判断。`running_process_detected=True` 且 `running_process_name=Chowdren` 是正常状态。
- `frontmost_process=Chowdren` 只能说明窗口聚焦；能否读状态、能否移动，还要看 `save_state_available`、`inspect_state` 和后续 `try_moves` 结果。

## 地图与普通关卡的区分

- 如果当前关卡是世界地图或 overworld，例如 `106level`、`177level`，不要按普通 Baba 关卡求解。
- 地图上没有 Baba 对象不是错误。地图的可控对象是 live-state 里的 `cursor`，控制模型是 `cursor is select`。
- 地图状态下使用 `navigate_next` 或 `map_route` 进入未完成关卡；进入后再读取普通关卡规则，再开始本关 benchmark。
- 不要自己从所有可见 `level` 单元里猜目标。地图上会显示很多当前不可达的关卡；以 `suggest_next_action` 的 `route_target` / `route_moves` 或 `map_route` 输出为准。
- 大地图通过 `0level` 后，典型下一关是 `1level`，坐标 `(11,14)`；从 `0level` 坐标 `(10,16)` 的路线是 `right,up,up,enter`。
- 在关卡内或下级地图内需要返回上级地图时，用 `return_to_map`。底层按键是 `esc,down,enter`。

不要在地图或下级地图上开始关卡 benchmark。`start_benchmark` 如果检测到当前是地图，会提示先 `navigate_next`，避免把地图当普通关卡计分。

## Baba 基础规则提示

- 规则通常由可见文字组成，形式是 `NOUN IS PROPERTY`。
- `YOU` 标记可控制对象；`WIN` 标记胜利对象；`STOP` 阻挡移动；`DEFEAT` 会消灭 `YOU`。
- `SHUT` 和 `OPEN` 接触时会互相移除，例如钥匙开门。
- 文字默认可推动。`TEXT IS PUSH` 是基础规则，可能生效但不会在关卡里显式摆出来。
- `PUSH` 的含义是：`YOU` 对象朝某方向移动时，可以把对应物体或文字向前推一格，前提是整条被推动链背后有空位。
- 如果推动链背后是 `STOP`、地图边界或不可推动阻挡物，推动不会发生。
- 推动文字可以创建或打断规则；移动 `IS`、`YOU`、`WIN`、`STOP`、`PUSH`、`OPEN`、`SHUT` 或名词文字通常是解题核心。

## 交互式解题循环

- 不需要先知道完整解法。先读状态，提出一个能被状态验证的小假设。
- 有明确预期时，不必一步一读；可以走到下一个有意义变化为止，例如 `left*3` 推开某个 `IS`。
- 优先让游戏动起来：短行动段比重计算搜索更适合直播和小模型接手。
- 每次 `try_moves` 后读 delta：规则新增/消失、目标对象移动、对象消失、完成态变化。
- 如果分支错了，用 `restart_level` 回到干净状态，再缩短或修正假设。
- 只有当问题主要是移动少量文字、目标规则明确、且搜索模型覆盖这些机制时，才使用重搜索。

## 解题效率协议

有些模型会把 `第一性原理` 和 `MECE` 理解成“先在脑内证明完整解法”。本项目不要这样做。除非用户明确要求讲解推理过程，否则每轮解题只输出并执行一个短反馈循环：

```text
观察：当前最关键的 1-3 个事实。
假设：这段短动作预期会改变什么。
动作：try_moves/map_route/restart_level 的一个命令，普通关卡动作段优先控制在 1-8 步。
结果：只读 delta，决定继续、缩短、撤回或重启。
```

- 不要在执行前手工推演超过 8 步；超过就拆成两个可验证动作段。
- 不要枚举所有可能规则排列、所有坐标路线、所有 “maybe” 分支。按 MECE 分清主要类型后，选择最便宜、最可观测的一类先试。
- 如果连续两段动作没有带来规则变化、关键对象移动、位置改善或完成态变化，停止脑内补救，先 `restart_level` 或回到上一个干净检查点。
- 如果一句话里第二次出现 “let me think / 让我再想 / 这很复杂 / getting complicated”，立刻把问题改写成一个更短的可验证动作，而不是继续推演。
- 读完 `baba_try.py` 的 delta 后，以 delta 为事实来源，不再复述完整坐标模拟；下一轮只解释和 delta 直接相关的差异。
- 可以记录学到的通用机制，但不要把记录文件写成完整内心独白或关卡解法剧透。

## 记录要求

当前 run 目录来自 `baba_config.json` 的 `current_run_id`，路径形如：

```text
runs/<number_agent_model>/
```

例如 `runs/001_codex_gpt55/` 或 `runs/002_claude_sonnet/`。不要写入固定的 `default_run_id`。

每过一关，当前 run 目录里的四个文件都要更新：

- `baba_benchmark_log.md`：机械 benchmark 事实、评分步数、证据。
- `baba_level_notes.md`：关卡路线、关键检查点、坐标和结果。
- `baba_learned_rules.md`：可复用经验；没有新经验时写明没有。
- `baba_growth_diary.md`：第一人称学习成长日记，使用用户的语言，不要写成路线日志。

评分字段约定：

- `score_steps` 是主排序字段，越小越好。
- 优先用本关刚刚 win 时 live state 的 `turn` 作为 `score_steps`，来源记为 `live_state_turn`。
- 如果 live state 的 `turn` 不可用，回退到验证路线展开步数，来源记为 `expanded_route_steps`。
- 实测 undo 会把局面撤回，但不会把 live state `turn` 撤回；undo 本身不额外加一回合。
- `elapsed_seconds` 只保留作排查基础设施差异的参考，不作为能力评分。

根目录 `runs/*.template.md` 是公开模板。真实 run 子目录默认不提交。

## Known Routes 边界

- `runs/<run_id>/baba_known_routes.json` 是独立 replay 数据，不是 benchmark 解题来源。
- `play_known_route` 可以用于回放或校验旧路线，但 benchmark 模式必须记录从当前状态学习、尝试、通过的过程。
- `record_pass` 会把 `last_score_steps` / `best_score_steps` 写回该 JSON，方便之后回放时看到步数成绩；这不改变 benchmark 禁止读路线解题的边界。

## 安装与配置边界

安装、配置、MCP server 配置、工具清单放在 `README.md`。本文件只规定 agent 接手后的目标、行为、风险边界和记录要求。
