# Agent Hypothesis Workflows

根据第一性原理，这份文档只解决一个问题：读完当前状态后，如何选一个便宜、可观测、可回滚的下一步。

## 何时用哪个入口

| 情况 | 入口 | 成功标准 |
| --- | --- | --- |
| 已有明确预期 delta | MCP `check_moves` 或 `scripts/baba_action_check.py` | 预期规则、对象移动、对象消失或 completion status 命中 |
| 需要看完整原始变化 | MCP `try_moves` | 读到 rules added/removed、moved units、disappeared units |
| 不知道下一步该试什么 | `python3 scripts/baba_suggest_hypotheses.py --top 8` | 得到少数候选假设，再转入 `check_moves` |
| 目标是构造文字规则 | `python3 scripts/baba_search_route.py --analyze`，必要时读 `docs/baba_route_search_method.md` | 打印路线可读，且执行前预期清楚 |
| 已有 `SHUT` + `OPEN` 思路但不知道撞哪里 | `python3 scripts/baba_rank_breakout_targets.py --subject wall --top 8` | 找到真正扩大可达区的阻挡物 |
| 实验破坏局面 | `restart_level` | 回到干净状态 |

## 假设生成脚本

当读完当前状态但还不知道下一步该试什么时，先运行：

```bash
python3 scripts/baba_suggest_hypotheses.py --top 8
```

这个脚本不是求解器，也不负责证明路线。它只做第一层功能筛选：从当前 live state 里识别 `YOU`、`PUSH`、`OPEN`、`STOP`、`DEFEAT` 等信号，按少数高价值模板生成候选假设，例如：

- `阻挡物 IS SHUT` + `可移动工具 IS OPEN`
- `当前可控对象 IS WIN`
- `某个对象 IS YOU`
- 打断可见的 `X IS STOP`

脚本输出的 `search_next` 只能作为候选路线生成入口，不能直接当事实。每个候选仍必须进入短反馈循环，用 `check_moves` / `scripts/baba_action_check.py` 验证真实 delta。

常用命令：

```bash
python3 scripts/baba_suggest_hypotheses.py --top 5
python3 scripts/baba_suggest_hypotheses.py --json --top 5
```

如果第一候选是类似 `wall is shut + star is open`，下一步不是穷举所有文字排列，而是分别验证这些目标规则是否能被短路线构造；构造成功后再验证实体交互是否真的打开通路。

## 破墙目标排序

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

排序结果只能决定“优先撞哪一格墙/门”，不能替代真实验证。选中候选后仍要用 `check_moves` / `scripts/baba_action_check.py` 验证工具和阻挡物是否真的一起消失，再读状态确认可达区域或 completion status。
