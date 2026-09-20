# 直播反馈与中断恢复

已有安全、可观察假设时，争取在观察后 10 秒内调用下一段 `check_moves`，每段通常 1–8 步。这是决策目标，不是脚本能保证的外部调度时限。

## 搜索

`baba_search_route.py --from-live-state --time-limit 5` 默认固定现有 YOU 文字；只有明确需要时加 `--move-you-text`。用 `--target-start X,Y --target-dir horizontal` 缩小目标位置。统一协作式预算覆盖模式、分配、启发式、可达区域与求解；不是操作系统级硬实时截止。每秒 stderr 报阶段和计数。时间或规模耗尽返回退出码 3、`budget_exhausted`，不代表无解。

`candidate_moves` 若非空，是模型中发现的首个合法推动之前最多 8 步，仅供形成下一短实验的假设，必须重新核对 live 状态并声明预期后用 `check_moves` 验证。预计算期间超时可能没有候选，不能凭空补路线。

## 命令行

```
python3 scripts/baba_action_check.py 'right*2' --expect-moved baba --action-id my-action
python3 scripts/baba_try.py --status my-action
```

动作检查持续转发子进程输出。日志在当前 run 的 `actions/<action-id>.json`，保存动作前后状态、已确认步数、待确认按键及 turn/sequence。普通关卡仍要求 active benchmark 匹配，completion status 3 才算通关。

## MCP

`check_moves` 设置 `background=true` 返回句柄，不等待整段；之后用 `action_status(action_id)` 查询进度与输出尾部。`cancel_action(action_id)` 请求在下一个按键前停止，当前在途按键仍要等待确认。后台执行不受客户端停止等待影响，需显式取消。

同一动作 ID 不能再次后台提交。MCP 重启后持久化日志仍可查询，旧进程的退出码不可恢复，不能把未知退出码当成功。若尚无 journal，用 output_tail 诊断启动或参数错误，不自动重发。

中断后先查询：

- `worker_active=true`：等待或请求取消，不重发。
- `pending` 非空：按键发送结果未确认，禁止自动重放；检查真实状态后再选择新动作。
- 已完成：读取原结果；CLI 用原 ID、原动作、原预期及 `--resume` 可读取缓存 delta。
- 已确认前缀：用同 ID、完整原动作、原预期、`--resume`；仅在当前状态指纹匹配时继续。规则变化会先停在 checkpoint。
- 已取消：取消标记保留，resume 不继续发送；观察当前状态后用新 ID 发起新的短实验。

## 等待原因

`submitted` 是 MCP 已启动检查进程；`accepted` 是动作进程开始处理；`focusing` 是窗口准备；`sending` 是发送按键；`waiting_state` 是等待导出；`confirmed` 表示已确认；`checkpoint` 是规则变化后的停点。

`state_missing` 表示文件缺失，`state_parse_failed` 表示快照解析失败，`state_unchanged` 表示可读但未更新，`state_incomplete_turn` 表示只观察到中间导出。失焦返回 `window_unfocused`。

审批/工具调度发生在进程启动前，脚本无法测量，标记 `external_not_measured`；不能将这段时间算成搜索、按键或状态读取耗时。

## 验证边界

离线测试：`python3 -m unittest discover -s tests -v`。真实输入延迟与段间 P95 必须另做现场测量；模拟测试通过不代表已达到 10 秒目标。常驻按键发送器暂不引入，避免在主要反馈问题未实测前增加输入控制复杂度。
