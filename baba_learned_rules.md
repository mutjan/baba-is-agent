# Baba Is You Learned Rules

## 验证原则

- 不把命令退出码当作游戏响应。`frontmost=Chowdren` 只说明事件发给了游戏进程，不说明关卡状态改变。
- 本环境不要用截图验证 Baba 窗口。优先看用户观察、存档文件和解析器输出。
- 关卡完成的可靠证据是存档里对应关卡变为完成态，例如 `0level=3`、`1level=3`。
- 当前关卡的可靠证据是存档 `[world] Previous=...`，再由 `parse_baba_level.py` 解析对应 `.l/.ld`。

## 输入控制

- `osascript/System Events` 可以执行，但 Baba/Chowdren 不可靠接收这些按键。
- `CGEventPost(kCGHIDEventTap)` 已验证能让 Baba 实际移动。
- 固化入口：

```bash
python3 baba_send_keys.py 'right,left'
```

## 选关地图

- 存档里的 `leveltree` 指向当前世界地图关卡，例如 `106level`。
- 地图 `.ld` 的 `[general] selectorX/selectorY` 是地图光标默认锚点。
- `[levels]` 保存关卡节点坐标，必须按 `[general] levels` 限制数量；文件后面可能残留旧条目。
- `[paths]` 保存可走路径坐标，必须按 `[general] paths` 限制数量；文件后面也可能残留旧路径。
- `[paths]` 的 `requirement` 要结合 `[world_prize] total` 判断。需求数未满足的路径不能算作当前可见/可走路径。
- 存档里的 `levelsurrounds` 可用来反推或校验当前地图光标周围的 level/path 分布。
- 固化入口：

```bash
python3 baba_map_route.py
python3 baba_map_route.py --execute
```

已验证从主地图进入 `1level / where do i go?` 的检测结果：

```text
cursor=(10, 16) source=levelsurrounds
target=1level coords=[(11, 14)]
moves=right,up,up,enter
```

## 规则推理

- 文字块默认可推，即使没有显式 `TEXT IS PUSH`。
- 规则只在 `NOUN IS PROPERTY` 横向或纵向连续排列时成立。
- 打断规则中的任意一格文字，规则立刻失效。
- `WALL IS STOP` 失效后，Baba 可以穿过墙；文字也可以被推到墙所在格上。
- 对象本身不是胜利条件；必须先形成类似 `FLAG IS WIN` 的规则，再让 Baba 碰到 flag。
- `WATER IS SINK` 会让进入水格的对象和水一起消失。可以用 `ROCK IS PUSH` 把 rock 推进水里，清出通路。
- 如果 `ROCK IS WIN` 成立但 `ROCK IS PUSH` 已失效，Baba 可以直接走到 rock 上获胜。
- 如果一个词被推离原规则，比如把 `ROCK` 从 `ROCK IS PUSH` 推走，这条规则会立刻失效。

## Level 0: baba is you

初始规则：

```text
BABA IS YOU
FLAG IS WIN
WALL IS STOP
ROCK IS PUSH
```

路线：

```bash
python3 baba_send_keys.py 'right*8' --delay 0.12
```

结果：`0level=3`。

## Level 1: where do i go?

初始规则：

```text
BABA IS YOU
WALL IS STOP
```

关键目标：

1. 推开下方 `WALL IS STOP` 中的 `IS`，让墙不再 stop。
2. 把这个 `IS` 推到 `text_flag` 右侧，形成 `FLAG IS ...`。
3. 把 `WIN` 推到 `IS` 右侧，形成 `FLAG IS WIN`。
4. Baba 碰 flag。

已验证路线：

```bash
python3 baba_send_keys.py 'left*5,down,left,up*5,right*7,up*3,left*5,up,left,down*2,right,down,right' --delay 0.12
```

路线后的关键文字坐标：

```text
text_flag: (8,9)
text_is:   (9,9)
text_win:  (10,9)
flag:      (12,9)
```

结果：`1level=3`。

## 固定路线脚本

已知关卡路线统一入口：

```bash
python3 baba_play_known_route.py --list
python3 baba_play_known_route.py --level 1level
python3 baba_play_known_route.py --level 1level --execute
```

注意：固定路线假设游戏已经在对应关卡内，且处于该关初始状态。从地图进入关卡应先用 `baba_map_route.py`。

## Level 3: out of reach

初始规则：

```text
BABA IS YOU
WALL IS STOP
WATER IS SINK
ROCK IS PUSH
FLAG IS WIN
```

关键目标：

1. 把一颗 rock 推进出口处的 water，利用 `WATER IS SINK` 清出通路。
2. 去右下文字区，把 `ROCK` 文本向下推到 `FLAG IS WIN` 的第一格。
3. 形成 `ROCK IS WIN`，同时打断 `ROCK IS PUSH`。
4. 回到上方房间，走到剩下那颗 rock 上获胜。

已验证路线：

```bash
python3 baba_send_keys.py 'down*3,right*4,up,left*2,up,left,down*7,right*2,up*3,right,down*3,left*3,up*8,right*2' --delay 0.12
```

路线后的关键变化：

```text
text_rock: (14,13)
text_is:   (15,13)
text_win:  (16,13)
remaining rock: (13,4)
```

结果：`3level=3`。
