# Baba Agent Contract

根据第一性原理，本项目的目标不是复现已有路线，而是让 agent 从当前真实状态出发，交互式学习并通关 Baba Is You 关卡，同时留下可验证的 benchmark 记录。

## 目标与硬标准

- 每次接手先确认真实状态：配置、当前 save、当前关卡、初始规则、是否在地图。
- Benchmark 是从零开始的学习和通关能力测试，不要把当前 run 目录里的 `baba_known_routes.json` 当成解法来源。
- 通关证据只有一个硬标准：对应关卡 save completion status 变成 `3`。
- Benchmark 主评分是通关步数 `score_steps`，不是墙钟时间；墙钟用时只作辅助元数据。
- 每过一关，记录本关 `score_steps` 并更新当前 run 目录里的记录文件。
- 回答用户时使用用户的语言；本仓库协作默认每次回答以“根据第一性原理……”开头。

## 输出与决策原则

- 先确认真实目标、约束和成功标准，不要套用惯例。
- 如果目标、成功标准或风险边界不清晰且会影响实现方向，先向用户提问。
- 如果目标清晰但当前路径不是最简单、低风险、可验证的方案，直接指出更好的替代方案。
- 需要决策时按 MECE 原则覆盖主要可能性。
- 默认简洁输出：结论、关键理由、改动点、验证结果。
- 第一性原理在本项目里等于寻找最短可验证反馈回路，不等于穷举所有路线或长篇证明。

## 启动决策表

| 当前状态 | 下一步 |
| --- | --- |
| MCP 工具可用 | 先 `app_status`，再 `inspect_state`；不确定下一步时用 `suggest_next_action` |
| MCP 不可用或正在调试 MCP wrapper | 回退到 `python3 start_benchmark.py ...` 或 `python3 scripts/...`，并说明原因 |
| 新 clone 或新 agent 接手 | 优先 MCP `start_benchmark`；裸脚本 fallback 是 `python3 start_benchmark.py --run-id 001_agent_model` |
| 只做安装后干跑检查 | `python3 start_benchmark.py --dry-run --skip-primer --no-inspect` |
| 当前是世界地图或 overworld | 不要开始关卡 benchmark；用 `navigate_next` 或 `map_route` 进未完成关 |
| 进入普通关卡后没有 active benchmark | 唯一下一步是 `start_benchmark`，不是分析关卡 |
| `active_state_mismatch=true` | 不继续解题，不绕过记录；按脚本提示用 `--force-new` 修正 active 记录 |
| 已经胜利，completion status 是 `3` | 调用 `record_pass`，然后更新当前 run 记录 |
| 不知道该试什么 | 先读 `docs/agent_hypothesis_workflows.md`，再选一个短 `check_moves` 验证 |

## MCP 优先工具顺序

1. `app_status`：确认游戏进程和状态文件是否可读。
2. `inspect_state`：确认当前 live level、规则、对象和地图/关卡类型。
3. `suggest_next_action`：不确定下一步时先调用它。
4. `set_current_run_id`：仅当当前 run id 不对或为空。
5. `start_benchmark`：普通关卡开始计分前必须运行。
6. `check_moves`：默认动作入口；先声明一个预期 delta，再验证短行动段。
7. `try_moves`：仅在调试原始 delta 或没有明确预期时使用。
8. `restart_level`：实验把局面弄坏或需要回到干净检查点时使用。
9. `return_to_map`：需要从关卡或下级地图回到上级地图时使用。
10. `navigate_next` / `map_route`：当前状态是地图时进关。
11. `record_pass`：仅当 completion status 已经是 `3`。

## 地图与关卡边界

- 世界地图或 overworld 示例：`106level`、`177level`。地图上没有 Baba 对象不是错误，可控对象是 live-state 里的 `cursor`，控制模型是 `cursor is select`。
- 地图上会显示很多当前不可达的关卡；不要自己从所有可见 `level` 单元里猜目标。以 `suggest_next_action` 的 `route_target` / `route_moves` 或 `map_route` 输出为准。
- `navigate_next` / `map_route --execute` 只负责进关，不等于开始计分。进入普通关卡后，先运行 MCP `start_benchmark` 或裸脚本 fallback。
- 大地图通过 `0level` 后，典型下一关是 `1level`，坐标 `(11,14)`；从 `0level` 坐标 `(10,16)` 的路线是 `right,up,up,enter`。
- 在关卡内或下级地图内需要返回上级地图时，用 `return_to_map`。底层按键是 `esc,down,enter`。

## 短反馈解题循环

除非用户明确要求讲解推理过程，否则每轮只输出并执行一个短反馈循环：

```text
观察：当前最关键的 1-3 个事实。
假设：这段短动作预期会改变什么。
动作：check_moves/map_route/restart_level 的一个命令，普通关卡动作段优先控制在 1-8 步。
结果：只读 delta，决定继续、缩短、撤回或重启。
下一步：继续当前目标、换目标，或回到干净检查点。
```

- 每轮只选一个可观测目标：改变一条规则、移动一个关键文字或物体、接近一个目标区域、验证一个阻挡是否成立。
- 有明确预期时，不必一步一读；可以走到下一个有意义变化为止。
- 不要在 hidden thinking 里验证路线。验证必须交给 `check_moves` / `scripts/baba_action_check.py`，并带上 `--expect-*` 预期。
- 不要在执行前手工推演超过 8 步；超过就拆成两个可验证动作段。
- 连续两段动作没有带来规则变化、关键对象移动、位置改善或完成态变化时，先 `restart_level` 或回到上一个干净检查点。
- 读完脚本结果后，以脚本输出为事实来源，不复述完整坐标模拟；下一轮只解释和 delta 直接相关的差异。

## 直播反馈预算

- 已有安全、可观测假设时，直接执行 1-8 步实验；正常阶段争取在观察后 10 秒内发起下一段动作。此项是决策目标，不能靠空走、盲目重试或跳过计分满足。
- 不为一次短实验寻找整关最优路线；需要搜索时默认总预算 5 秒，先固定当前 YOU 文字。只在结果说明需要扩大范围时允许移动 YOU 文字或提高预算。
- 长等待要区分搜索、工具审批、执行、等待状态；不要把所有停顿都说成游戏读取失败。脚本不能承诺控制外部审批耗时。
- 中断后先查询原 action 的进度；已完成不重发，有未确认按键时停止自动重放。先核对当前真实状态，再决定后续动作。
- 具体接口与限制见 `docs/live_feedback_protocol.md`。

## 按需参考

- Baba 基础规则和移动风险：`docs/agent_baba_primer.md`
- 假设生成、破墙排序、搜索入口选择：`docs/agent_hypothesis_workflows.md`
- 可复用 live-state 解题方法：`docs/baba_state_guided_play_method.md`
- 关卡解析方法：`docs/baba_level_parsing_method.md`
- 文字规则搜索方法：`docs/baba_route_search_method.md`
- 安装、配置、MCP server 配置、工具清单：`README.md`

只在当前任务需要时打开参考文件。主反馈回路永远优先于泛读文档。

## 记录要求

当前 run 目录来自 `baba_config.json` 的 `current_run_id`，路径形如 `runs/<number_agent_model>/`。不要写入固定的 `default_run_id`。

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
- 根目录 `runs/*.template.md` 是公开模板。真实 run 子目录默认不提交。

## Known Routes 边界

- `runs/<run_id>/baba_known_routes.json` 是独立 replay 数据，不是 benchmark 解题来源。
- `play_known_route` 可以用于回放或校验旧路线，但 benchmark 模式必须记录从当前状态学习、尝试、通过的过程。
- `record_pass` 会把 `last_score_steps` / `best_score_steps` 写回该 JSON，方便之后回放时看到步数成绩；这不改变 benchmark 禁止读路线解题的边界。
