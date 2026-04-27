# Baba Is You Level Notes Template

Store concrete per-level facts for one agent run here.

Recommended path for a real run:

```text
runs/<number_agent_model>/baba_level_notes.md
```

## Level <id>: <name>

初始规则：

```text
<RULE>
```

关键目标：

1. <state-readable objective>
2. <next checkpoint>

验证路线：

```bash
python3 scripts/baba_send_keys.py '<moves>' --hold-ms <ms>
```

关键验证：

```text
<coordinate/rule/completion evidence>
```

结果：`<level>=3`，评分步数 `<score_steps>`（来源：`<score_source>`），路线展开 `<route_steps>` 步。
