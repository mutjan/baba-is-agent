# Baba Is You Learned Rules Template

Store reusable lessons learned by one agent run here. Keep this file generic:
do not copy full per-level routes unless the route teaches a reusable rule.

Recommended path for a real run:

```text
runs/<number_agent_model>/baba_learned_rules.md
```

## 验证原则

- 通关证据来自存档完成态 `3`，不是按键命令退出码。
- Benchmark 主评分来自通关步数 `score_steps`，不是墙钟时间。
- 新关卡先读当前状态和初始规则，再尝试动作段。
- 动作段停在有意义的状态变化处：规则增删、关键对象移动、对象消失或通关。

## 输入控制

- 使用 CGEvent 输入路径。
- 默认读取 `baba_config.json` 的 `input_delay`。
- 长路线如果丢键，优先提高 `hold_ms` 或 `input_delay`，并记录原因。

## 规则推理

- <reusable lesson>

## 脚本、JSON 与 Markdown 边界

- 脚本负责机械事实：读状态、发按键、等待刷新、比较差异、查询完成态、地图寻路、约束搜索。
- `runs/<number_agent_model>/baba_known_routes.json` 负责该 run 的机器可读已知路线复放数据，不作为 benchmark 解法来源。
- Markdown 负责判断经验：为什么选这个动作段、哪些分支失败、何时停、何时重置。
