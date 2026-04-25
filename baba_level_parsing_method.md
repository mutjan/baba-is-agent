# Baba Is You Level Parsing Method

## 目标

把本机 Baba Is You 的当前关卡解析成可读文本地图、对象坐标和当前有效规则，用来辅助分析“当前这关怎么过”。

## 数据位置

- 游戏关卡目录：`/Users/lzw/Library/Application Support/Steam/steamapps/common/Baba Is You/Baba Is You.app/Contents/Resources/Data/Worlds`
- 存档目录：`/Users/lzw/Library/Application Support/Baba_Is_You`
- 当前存档槽和世界：`SettingsC.txt` 的 `[savegame] slot` 与 `world`
- 当前关卡 id：对应槽位文件，比如 `1ba.ba` 中当前 world 段落下的 `Previous`

例：`SettingsC.txt` 显示 `slot=1`、`world=museum`，然后 `1ba.ba` 的 `[museum] Previous=y128level`，当前关卡就是 `Worlds/museum/y128level.l` 和 `Worlds/museum/y128level.ld`。

## 文件格式

每个关卡通常有三类文件：

- `.ld`：INI 风格文本，包含关卡名、对象列表、对象 tile 编码、颜色和特殊设置。
- `.l`：二进制地图，包含地图尺寸和压缩后的图层数据。
- `.png`：关卡缩略图，只适合人工核对，不作为结构化解析来源。

全局默认对象来自 `Data/values.lua` 的 `tileslist`；`.ld` 的 `[currobjlist]` 会覆盖/补充当前关卡对象。`Nname` 是对象名，`Ntile=x,y` 是对象 tile。`.l` 图层格子里的数值按 `y * 256 + x` 对应这个 tile。

`.l` 的关键结构：

- 文件头包含 `LAYR` chunk。
- `LAYR` 后可读出地图宽高。
- 每个 `MAIN` chunk 后面是 4 字节小端压缩长度，再跟 zlib 数据。
- zlib 解压后是一组 16 位小端整数，每个整数对应一个格子。
- `65535` 表示 void，`0` 表示 empty。
- 不要只读 `[currobjlist]`：像 `0level` 这种基础关，关卡文件只列部分对象，`wall`、`text_win`、`text_stop` 等需要从 `values.lua` 的全局 tile 表补齐。

## 使用脚本

解析当前正在玩的关卡：

```bash
python3 parse_baba_level.py
```

解析指定关卡：

```bash
python3 parse_baba_level.py --world museum --level y128level
```

输出全部图层：

```bash
python3 parse_baba_level.py --world museum --level y128level --all-layers
```

## 输出说明

脚本会输出：

- 当前 `world`、`level`、关卡名、地图尺寸、图层数。
- `Active rules`：横向或纵向成立的 `A IS B` 规则，带起点坐标。
- 文本地图：第一行是 x 坐标末位，左侧是 y 坐标。
- `Positions`：每种对象的全部坐标，格式为 `(x,y,L层号)`。

常用符号：

```text
# wall
B baba
K keke
R rock
I ice
F fruit
, grass

b text_baba
k text_keke
r text_rock
i text_ice
f text_fruit
w text_wall
T text_text
= text_is
y text_you
W text_win
x text_stop
p text_push
l text_float
t text_tele
s text_sink
```

## 解题流程

1. 先运行脚本确认当前关卡，而不是靠记忆猜。
2. 读 `Active rules`，确认初始目标：谁是 `YOU`，谁是 `WIN`。
3. 看 `Positions`，找到 `YOU`、`WIN`、障碍物和可推文字。
4. 用文本地图按坐标推演路线。
5. 如果涉及 `FLOAT`、`TELE`、`SINK`，优先核对规则层级和对象是否同层/同浮空状态。

## 已验证样例

当前已验证 `museum/y128level`，关卡名 `reunion`：

```bash
python3 parse_baba_level.py --world museum --level y128level
```

可正确读出：

- `V (19,5): keke is win`
- `H (7,11): ice is tele`
- `V (5,14): text is float`
- `H (13,12): baba is you`
- `H (9,13): rock is push`

这个样例也确认了一个坑：不能假设地图宽度是 35。必须从 `.l` 的 `LAYR` 头读真实宽高，否则坐标和规则都会错。
