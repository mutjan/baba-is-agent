# Baba Is You Control Handoff

## 目标

探索一个比 `baba_is_eval` 更稳、更快的方式，让 Codex 能辅助玩 Baba Is You：

1. 读取当前关卡真实状态。
2. 分析规则和地图。
3. 必要时直接控制游戏输入。
4. 尽量降低脆弱窗口聚焦、文件轮询和命令同步问题。

## 当前状态

当前工作目录：

```text
/Users/lzw/Documents/New project 2
```

当前游戏状态已确认：

```bash
python3 parse_baba_level.py
```

最近输出显示：

```text
slot=2 world=baba level=0level name=baba is you
size=35x20 layers=2
```

当前新存档在 `slot=2`，世界是 `baba`，关卡是 `0level`。

已验证 macOS 辅助功能权限可用，但要区分两层输入：

- `osascript/System Events` 可以执行且不报错，但 Baba/Chowdren 不会可靠地把它当成游戏输入。
- `CGEventPost(kCGHIDEventTap)` 发送的低层键盘事件已被游戏接收，用户肉眼确认 Baba 先右左移动归位，随后单独向右移动一格。
- 当前不要再用截图验证游戏画面；本环境对 Baba 窗口截图不可靠。验证应优先使用用户观察、存档变化，或后续 Lua 状态导出。

失败过的 AppleScript 按键方式：

```bash
osascript -e 'tell application "Baba Is You" to activate' \
  -e 'delay 0.15' \
  -e 'tell application "System Events" to key code 124' \
  -e 'delay 0.08' \
  -e 'tell application "System Events" to key code 123'
```

这个方式的验证结果只能说明系统接受事件，不能说明游戏接收：

```text
exit=0
frontmost process=Chowdren
```

`Chowdren` 是 Baba Is You 的实际游戏进程。

已验证成功的低层输入方式：

```bash
clang -Wall -Wextra -framework ApplicationServices baba_cgevent_keys.c -o baba_cgevent_keys
./baba_cgevent_keys --delay-ms 120 right left
./baba_cgevent_keys --delay-ms 120 right
python3 baba_send_keys.py 'right,left'
```

用户观察结果：

```text
right,left: Baba 右左移动并归位
right: Baba 向右移动一格
```

## 已有文件

- `parse_baba_level.py`
  - 只读解析当前 Baba Is You 存档。
  - 自动读取 `SettingsC.txt` 的当前 `slot/world`。
  - 自动读取对应存档文件里的 `Previous` 关卡。
  - 解析 `.ld` 和 `.l`。
  - 从 `Data/values.lua` 读取全局 tile 表，再用关卡 `[currobjlist]` 覆盖。
  - 输出 active rules、文本地图和对象坐标。

- `baba_level_parsing_method.md`
  - 记录关卡解析方法、文件路径、`.l`/`.ld` 格式、坐标说明和使用命令。

- `baba_cgevent_keys.c`
  - 使用 macOS CoreGraphics `CGEventPost(kCGHIDEventTap)` 发送低层键盘事件。
  - 这是目前确认能控制 Baba Is You 的输入方式。

- `baba_send_keys.py`
  - Python 包装脚本。
  - 默认编译并调用 `baba_cgevent_keys`。
  - AppleScript 只用于激活游戏窗口；`--method applescript` 仅保留为对照，不推荐。

- `baba_map_route.py`
  - 只读解析当前存档和地图 `.ld` 文件。
  - 从当前 `leveltree` 地图的 `selectorX/selectorY`、`levels`、`paths` 和存档 `levelsurrounds` 推导地图光标位置。
  - 会按 `[general] levels/paths` 裁剪残留条目，并按 `[world_prize] total` 过滤未满足 `requirement` 的路径。
  - 默认选择当前存档中已解锁但未完成的下一关。
  - 输出并可执行进入下一关的按键序列。
  - 已验证从世界地图进入 `1level / where do i go?`：
    `right,up,up,enter`。

- `baba_play_known_route.py`
  - 保存已验证关卡固定路线。
  - 默认读取当前存档 `Previous`，也可用 `--level` 指定关卡。
  - `--execute` 会调用 `baba_send_keys.py` 发送路线。
  - 已固化 `0level`、`1level` 和 `3level`。

- `baba_learned_rules.md`
  - 记录目前学到的验证原则、输入控制、选关地图解析规则、Baba 规则推理和已通过关卡路线。

## 数据位置

游戏关卡目录：

```text
/Users/lzw/Library/Application Support/Steam/steamapps/common/Baba Is You/Baba Is You.app/Contents/Resources/Data/Worlds
```

游戏全局对象定义：

```text
/Users/lzw/Library/Application Support/Steam/steamapps/common/Baba Is You/Baba Is You.app/Contents/Resources/Data/values.lua
```

存档目录：

```text
/Users/lzw/Library/Application Support/Baba_Is_You
```

当前存档配置：

```text
/Users/lzw/Library/Application Support/Baba_Is_You/SettingsC.txt
```

## 已研究的开源方案

参考项目：

```text
https://github.com/lennart-finke/baba_is_eval
```

README 中说明它的方式是：

- 把 repo 放进 Baba Is You 的 `Data` 目录。
- 复制 `io.lua` 到 `Data/Lua/`，利用 Baba 的 mod hook。
- Lua 在 `level_start` 和命令执行后把游戏状态写入 `world_data.txt`。
- MCP 侧把命令写到 `baba_is_eval/commands/N.lua`。
- 游戏内 Lua 的 `always` hook 定期轮询命令文件，`dofile()` 后执行 `command("right", 1)` 等命令。

已发现的问题：

- 输入链路依赖文件轮询，README 里默认约 1 秒检查一次。
- `execute_commands()` 写命令文件后没有严格等待命令被游戏消费。
- 部分操作仍靠 `pyautogui` 点击固定坐标聚焦窗口。
- 菜单导航和进入关卡逻辑很硬编码。
- 状态写入走 INI 文件，读写同步容易慢或过期。

## 更好的候选方案

### 方案 A：CGEvent 低层按键输入 + 本地文件解析

这是当前最小可行方案。

控制：

- 使用 `osascript` 激活游戏窗口。
- 用 `CGEventPost(kCGHIDEventTap)` 发送方向键、撤销、重开等按键。

读取：

- 用 `parse_baba_level.py` 读取关卡初始布局。
- 用存档判断当前 `slot/world/level`。

优点：

- 不需要改游戏文件。
- 不需要安装 MCP server。
- 输入延迟低。
- 已验证游戏实际接收按键。

缺点：

- 只读关卡文件只能得到初始布局，不能自动知道每一步后的实时对象位置。
- 如果需要实时状态，仍需截图识别或 Lua 状态导出。

适合：

- 前几关、短路线、人工/模型根据初始状态推演后直接发按键。

### 方案 B：系统按键输入 + 薄 Lua 状态导出

这是推荐的中期方案。

控制：

- 仍使用 CGEvent 低层按键，不通过文件轮询输入。

读取：

- 写一个极薄的 `Data/Lua/codex_state.lua`。
- 在 `level_start`、`turn_end`、`undoed_after`、`level_restart`、`level_win` hook 中导出当前 `MF_getunits()` 状态。
- 状态文件可以写 JSON-like 或分隔符文本。

优点：

- 避免 `baba_is_eval` 最脆的“命令文件轮询输入”。
- 状态来自游戏内部对象表，比截图识别稳。
- 每个 turn 后导出，比每秒轮询更快、更同步。

缺点：

- 需要往游戏 `Data/Lua/` 增加一个 Lua 文件。
- 改 Lua 后通常要重启游戏才能加载。
- 仍需处理状态文件写入原子性和时间戳/turn id。

适合：

- 想让 Codex 连续多步自动玩，同时每步后校验真实状态。

### 方案 C：复用并改造 `baba_is_eval`

可作为备选。

改造方向：

- 保留它的状态导出逻辑。
- 删除或绕过 `commands/N.lua` 输入轮询。
- MCP 工具调用时改为 `osascript` 发按键。
- `execute_commands()` 必须等待 `turn_id` 或 `last_processed` 变化后再返回。

优点：

- 已有 MCP 包装。
- 状态导出字段比较完整。

缺点：

- 代码仍带着菜单导航、固定坐标聚焦、命令文件等旧假设。
- 不如从小脚本逐步长出来清晰。

### 方案 D：纯截图/视觉控制

不推荐作为主线。

优点：

- 不改游戏文件。
- 理论上能读实时画面。

缺点：

- OCR/图像识别成本高。
- Baba Is You 的规则块、小字、重叠对象都容易识别错。
- 比内部状态导出更慢、更脆。

## 当前推荐路径

推荐走方案 B，但按阶段推进：

1. 保持 `parse_baba_level.py` 作为静态/初始状态解析器。
2. 使用 `baba_send_keys.py` 发送输入：
   - `python3 baba_send_keys.py 'right,left,up'`
   - 默认走 CGEvent。
   - 激活 `Baba Is You` 后发送低层 key event。
   - 可选每步延迟。
3. 在选关地图上使用 `baba_map_route.py` 检测并进入下一关：
   - `python3 baba_map_route.py`
   - `python3 baba_map_route.py --execute`
   - 已验证输出 `right,up,up,enter` 后，存档 `Previous` 变为 `1level`。
4. 在已知关卡内可以使用固定路线脚本：
   - `python3 baba_play_known_route.py --list`
   - `python3 baba_play_known_route.py --level 1level --execute`
   - 注意固定路线假设游戏已经在对应关卡内，且关卡处于初始状态。
5. 如果需要自动多关，新增 Lua 状态导出：
   - 只导出状态，不接收命令。
   - 每次 turn 后写 `turn_id`。
   - Python 等到 `turn_id` 增加后再继续下一步。

## 按键映射

CGEvent/AppleScript 都使用同一套 macOS key code：

```text
left  = 123
right = 124
down  = 125
up    = 126
z/undo = 6
r/restart = 15
space/confirm = 49
return/confirm = 36
escape/menu = 53
```

示例：

```bash
python3 baba_send_keys.py 'right*3,up,left'
```

## 风险边界

- 不要绕过 macOS 安全限制；需要按键权限时让用户手动授予辅助功能权限。
- 不要直接改存档来“过关”，除非用户明确要求。
- 不要覆盖用户游戏文件；如果要放 Lua hook，先备份并说明改动。
- 不要信任固定地图宽度；必须从 `.l` 的 `LAYR` 头读取真实宽高。
- 不要只读关卡 `[currobjlist]`；基础对象需要从 `values.lua` 补齐。

## 下一步

`baba_send_keys.py` 已经写好。下一步是做端到端过关验证：

```bash
python3 baba_send_keys.py right,right,up,left
```

然后在 0level 上做端到端验证：

1. `python3 parse_baba_level.py`
2. 推导一条简单过关路线。
3. `python3 baba_send_keys.py ...`
4. 观察是否过关。

如果这一步稳定，再写 Lua 状态导出，不急着引入 MCP。
