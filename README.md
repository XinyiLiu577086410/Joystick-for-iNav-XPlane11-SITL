# hid-as-rx — Windows 分支

在 **Windows** 上用 HID 手柄/遥控器当接收机，驱动 **INAV SITL**，并把 **X-Plane 11**
当作飞行仿真器。

> 这是 `windows` 分支：进程管理、键盘输入、X-Plane 探测全部是 **Windows 原生实现**，
> 不与 macOS 共用同一份代码。macOS 版本保留在 `main` 分支，
> 原始文档见 [docs/README-macos.md](docs/README-macos.md)。

---

## 1. 组成

| 组件 | 作用 | 谁管理 |
|---|---|---|
| **X-Plane 11 / 12** | 飞机物理、画面、HITL 插件宿主 | 外部，`hidctl` 只读探测 |
| **INAV SITL**（Configurator 自带 `inav_SITL.exe`） | 飞控逻辑：接收机、混控、PID、导航 | `hidctl.cmd start sitl` |
| **`scripts/hid2msp.py`** | 手柄/键盘 → MSP 接收机（TCP 5762） | `hidctl.cmd start bridge` |
| **INAV Configurator** | 通过 TCP 5760 配置 SITL | 外部 |
| **INAV-X-Plane-HITL 插件** | X-Plane 里的飞机插件：传感器 + 控制 + OSD | X-Plane 加载 |

### 1.1 组件协作关系

四个 TCP 端口全在本机，每个 UART 同时只允许一个客户端：

| 端口 | UART | 客户端 | 协议 |
|---|---|---|---|
| 5760 | UART1 | INAV Configurator | MSP 配置 / CLI |
| 5761 | UART2 | X-Plane HITL 插件 | `MSP_SIMULATOR` |
| 5762 | UART3 | `hid2msp.py` | `MSP_SET_RAW_RC` |
| 5763 | UART4 | 无（SITL 自用） | MSP DisplayPort / HD OSD |

```text
X-Plane 11 ── HITL 插件 ── 5761 ── SITL UART2
     ▲                            │
     │ 控制量/OSD                  │ 5762 ── hid2msp.py ── 手柄/键盘
     └────────────────────────────┘
Configurator ── 5760 ── SITL UART1（配置/CLI）
SITL UART4 ── 5763（MSP DisplayPort 画布，插件通过 5761 读取）
```

关键点：

- 手柄不是 X-Plane 的摇杆，而是通过 `hid2msp.py` 变成 INAV 的 **MSP 接收机**；
- 插件把 SITL 的 roll/pitch/yaw/throttle 写进 X-Plane，再把 X-Plane 的姿态/传感器回传给 SITL；
- OSD 由插件绘制；SITL 用 UART4 维护 OSD 画布，插件通过 5761 的 `MSP_SIMULATOR` 读取；
- Configurator、插件、手柄桥各占一个 UART，不能共用。

### 1.2 运行时序

正常飞行时，50 Hz 循环：

1. `hid2msp.py` 读取手柄轴/按键，或读取键盘（仅 X-Plane 前台时）；
2. 通过 5762 发 `MSP_SET_RAW_RC`（CH1–CH9）；
3. SITL 做接收机解析、混控、PID、导航；
4. SITL 通过 5761 回 `MSP_SIMULATOR`（控制量、OSD、状态位）；
5. HITL 插件把控制量写进 X-Plane，并绘制 OSD；
6. X-Plane 把姿态/传感器数据回传插件，插件再通过 5761 回给 SITL。

启动顺序是：`hidctl start sitl` → 等 5760–5763 监听 → `hidctl start bridge` → 你在 X-Plane 里连 5761、Configurator 连 5760。

---

## 2. 安装与依赖

| 组件 | 要求 | 检查 |
|---|---|---|
| Windows | 10 / 11，64 位 | — |
| Python | 3.10+（本机 3.12） | `python --version` |
| INAV Configurator | **10.0.0**（自带 INAV 10 SITL） | `hidctl.cmd doctor` |
| X-Plane | 11.55+ 或 12 | `hidctl.cmd doctor` |
| HITL 插件 | v1.5.0（已装到 `NK_FPVSurfwing`） | `hidctl.cmd status` |
| pygame | 仅手柄模式需要 | `python -m pip install pygame` |

不需要真实飞控、真实接收机，也不需要自己编译 SITL 或插件。

键盘模式不需要 pygame，也不需要管理员权限；但默认**只在 X-Plane 是前台窗口时生效**，切到其他软件会自动暂停，避免误触。

### 2.1 X-Plane 11 / 12

1. 安装/确认 **X-Plane 11.55r2**（Steam 或独立版均可；X-Plane 12 也可，但插件要用对应版本）。
2. 找到 X-Plane 根目录，Steam 版通常是：

   ```text
   C:\Program Files (x86)\Steam\steamapps\common\X-Plane 11
   ```

3. 复制 INAV Surfwing 和 HITL 插件：

   ```powershell
   $XP = "C:\Program Files (x86)\Steam\steamapps\common\X-Plane 11"
   Copy-Item "3rdparty\INAV-X-Plane-HITL\release\Aircraft\Extra Aircraft\NK_FPVSurfwing" `
             "$XP\Aircraft\Extra Aircraft\" -Recurse
   ```

   插件本体在机型的 `plugins\INAV-X-Plane-HITL\64\win.xpl`，随机型一起复制即可。

4. 启动 X-Plane，设置 `Settings → General → Flight models per frame = 10`。
5. `New Flight → Select Aircraft`，勾选底部的 **`Show extra aircraft from old versions`**，
   选择 `Extra Aircraft → INAV Surfwing`。
6. 进入飞行后：`Plugins → INAV HITL/SITL → Link → Connect to SITL → 127.0.0.1:5761`。

### 2.2 INAV Configurator 10.0.0

安装 **INAV Configurator 10.0.0**，它自带 Windows SITL：

```text
C:\Program Files (x86)\INAV-Configurator_Win64_10.0.0\app-10.0.0\resources\sitl\windows\inav_SITL.exe
```

确认版本：

```powershell
& "C:\Program Files (x86)\INAV-Configurator_Win64_10.0.0\app-10.0.0\resources\sitl\windows\inav_SITL.exe" -v
```

`hidctl` 会自动探测 `Program Files`、`Program Files (x86)`、`%LOCALAPPDATA%\Programs`
下的 `INAV*` 目录；也可以用 `HIDCTL_SITL` 直接指定 exe：

```powershell
$env:HIDCTL_SITL = "D:\INAV\...\inav_SITL.exe"
```

> 本机还装有 Configurator 8.0.1（SITL 8.0.1）。HITL 插件 v1.5.0 官方面向 INAV 7/8；
> 如果 INAV 10 联调遇到协议问题，可以临时切到 8.0.1 做对照，但 eeprom 要按对应版本重建。
> 不要混用不同版本的 `plane.bin`。

### 2.3 Python

```powershell
python --version
python -m pip install --upgrade pip
```

`hid2msp.py` 只依赖标准库；只有手柄模式需要 pygame。

### 2.4 pygame

```powershell
python -m pip install pygame
```

如果 pip 不能写系统目录（例如受限环境），也可以把 wheel 解压到仓库的 `.deps\`，
`hid2msp.py` 会自动把 `.deps` 加进 `sys.path`：

```powershell
python -m pip download pygame --no-deps -d .
# 把 pygame-*.whl 重命名为 .zip 后解压到 .deps\
```

`.deps\` 已被 `.gitignore` 排除。

### 2.5 HID 手柄/遥控器（可选）

没有手柄时可以直接用键盘（见 4.3）。手柄可以是 USB 模拟器适配器，也可以是把遥控器当 USB HID 的设备。

先确认编号：

```powershell
python scripts\hid2msp.py --list
```

会打印设备名、轴数/按键数，并实时显示 `axes=[...] buttons=[...]`。轴编号因 SDL/Windows 而异，
换手柄或换机器后建议跑一次 `.\hidctl.cmd setup`。

---

## 3. 快速启动

```powershell
# 启动 SITL + 手柄桥
.\hidctl.cmd start

# 看状态
.\hidctl.cmd status
```

SITL 的路径会自动探测：`HIDCTL_SITL` 环境变量优先，否则在
`Program Files`、`Program Files (x86)`、`%LOCALAPPDATA%\Programs` 下找
`INAV*` 目录里的 `resources\sitl\windows\inav_SITL.exe`，多个版本时取版本号最高的。
本机探测结果可以用 `.\hidctl.cmd config show` 查看。

也可以直接用 Python：

```powershell
python hidctl.py start
python hidctl.py status
```

然后手动完成 X-Plane 侧：

1. X-Plane 11 → `Settings → General → Flight models per frame` = **10**；
2. `New Flight → Select Aircraft`，勾选底部的
   **`Show extra aircraft from old versions`**，选 **`Extra Aircraft → INAV Surfwing`**；
3. 进入飞行后：`Plugins → INAV HITL/SITL → Link → Connect to SITL → 127.0.0.1:5761`；
4. 需要改参数时，Configurator 连 **TCP `127.0.0.1:5760`**。

`sitl` 和 `bridge` 由 `hidctl.cmd` 管理；X-Plane 和 Configurator 由你自己启动。

### 3.1 启动/停止命令

```powershell
.\hidctl.cmd start              # SITL + bridge
.\hidctl.cmd start sitl         # 只启动 SITL
.\hidctl.cmd start bridge       # 只启动 bridge
.\hidctl.cmd start --follow     # 启动后持续跟随日志，Ctrl-C 只停止跟随

.\hidctl.cmd stop               # 先停 bridge，再停 SITL
.\hidctl.cmd restart            # 全部重启
.\hidctl.cmd restart sitl       # 只重启 SITL（bridge 自动重连）

.\hidctl.cmd logs bridge -n 100
.\hidctl.cmd logs all -f

.\hidctl.cmd config load      # 把 CLI 源文件写进 eeprom（详见第 5 节）
```

`start` 是幂等的；组件输出追加到 `logs\sitl.log`、`logs\bridge.log`，
PID 写到 `run\sitl.pid`、`run\bridge.pid`。

### 3.2 status 示例

```text
sitl    running  pid 5752  ports 5760,5761,5762,5763
bridge  running  pid 21376  target 127.0.0.1:5762  connected
eeprom  .\config\runtime\plane.bin  (32768 bytes, 2026-11-10 15:18:44)
config  .\config\hid2msp_inav.json
xplane  installed 11.55r2  (not running)  (external, not managed)
hitl    installed v1.5.0  link: disconnected  (X-Plane plugin)
```

- `xplane`：读 `X-Plane.exe` 的版本信息；运行中还能拿到 PID；
- `hitl`：在 `Aircraft\Extra Aircraft\*\plugins\INAV-X-Plane-HITL\64\win.xpl` 里找插件，
  版本从二进制里读；`link` 用 `netstat` 判断 5761 是否有 ESTABLISHED 连接；
- 退出码：SITL 运行且 bridge 已连接为 `0`，否则 `1`。

---

## 4. 通道定义

### 4.1 通道表

当前配置见 [config/hid2msp_inav.json](config/hid2msp_inav.json)：

| 通道 | 功能 | 来源 |
|---|---|---|
| CH1 | Roll | 手柄 axis 4 |
| CH2 | Pitch | axis 0 |
| CH3 | Throttle | axis 1 |
| CH4 | Yaw | axis 3 |
| CH5 | 旋钮三档原始指示 | axis 5，`tri` |
| CH6 | SWC → NAV WP | button 3，高=开 |
| CH7 | SWB → ARM | button 2，高=解锁 |
| CH8 | 六段模式 | axis 5，`multi` 6 档 |
| CH9 | NAV LAUNCH | 常量 2000 |

### 4.2 六段模式

| 旋钮 | CH8 | 模式 |
|---|---|---|
| 最低 | 1000 | ANGLE |
| 低 | 1200 | HORIZON |
| 中低 | 1400 | MANUAL |
| 中高 | 1600 | NAV CRUISE |
| 高 | 1800 | NAV POSHOLD |
| 最高 | 2000 | NAV RTH |

> CH9 常高意味着 NAV LAUNCH 永久启用，SITL 里解锁即进入起飞模式。
> 仅用于仿真，**不要照搬到真机**。

### 4.3 键盘控制（无手柄时自动启用）

键盘输入只在 **X-Plane 是当前最上层窗口** 时生效；切到浏览器、终端或其他软件时，
按键会被忽略，摇杆自动回中、油门保持、解锁状态不变，不会误触。

当前配置的键位：

| 键 | 功能 |
|---|---|
| `←` / `→` | Roll 左 / 右 |
| `↓` / `↑` | Pitch 上 / 下（当前配置把方向键对调了） |
| `Page Up` / `Page Down` | Yaw 左 / 右 |
| `1`–`6` | 六段模式：ANGLE / HORIZON / MANUAL / CRUISE / POSHOLD / RTH |
| `Ctrl+A` | 按一下切换解锁/上锁 |
| `Shift` | 按住增加油门 |
| `Ctrl` | 按住减少油门 |

行为：

- 初始油门 1000、CH7 上锁、CH8 为 ANGLE；
- 油门 > 1050 时拒绝解锁，并提示先降低油门；
- `1`–`6` 是按下沿触发，不是按住；
- 轴和油门按 `axis_rate` / `throttle_rate` 平滑变化，不会瞬间满舵；
- 键盘模式不控制 CH6 NAV WP，CH6 固定 1000；
- `Ctrl` 同时是“油门减少”和 `Ctrl+A` 解锁的修饰键：按 `Ctrl+A` 时油门会同时下降，
  对解锁反而安全，但飞行中不要误按 `Ctrl`；
- 默认只有 X-Plane 前台才响应，避免在浏览器/终端里误触。

每个键都可以改成 **组合键**，例如解锁用 `ctrl+shift+space`：

```powershell
.\hidctl.cmd setup keyboard
```

向导会逐个动作要求按键：

- 单个键：直接按，例如 `w`；
- 单个修饰键：直接按一下 `Shift` / `Ctrl`，会得到 `shift` / `ctrl`；
- 组合键：先按住 `Ctrl` / `Shift` / `Alt` / `Win`，再按主键；例如 `Ctrl+Shift+Space`；
- 纯修饰键组合也可以：按住 `Ctrl+Shift` 再松开，得到 `ctrl+shift`；
- `s` 跳过当前动作，`q` 退出且不写入；
- 结束后自动备份原配置、写入 `config\hid2msp_inav.json` 并校验。

配置里的键盘段：

```json
"keyboard": {
  "enabled": true,
  "source": "auto",
  "foreground_only": true,
  "window_process": "X-Plane.exe",
  "keys": {
    "arm": "ctrl+shift+space"
  }
}
```

- `foreground_only`：只在前台进程匹配时启用键盘；
- `window_process`：前台进程名，默认 `X-Plane.exe`；进程查询失败时会退回到窗口标题包含 `X-Plane` 或 `X-System` 的判断；
- `source` 三种值：`auto`（有手柄用手柄，否则键盘）、`hid`（强制手柄）、`keyboard`（强制键盘）。

改完执行：

```powershell
.\hidctl.cmd config check
.\hidctl.cmd restart bridge
python scripts\hid2msp.py --keys     # 不接 SITL，直接看键盘通道
```

注意：`--keys` 监视模式同样遵守 `foreground_only`，调试时要把 X-Plane 切到前台。

### 4.4 `hid2msp_inav.json` 字段

```json
{
  "host": "127.0.0.1",
  "port": 5762,
  "rate_hz": 50,
  "axes": [
    {"axis": 5, "channel": 1, "kind": "bipolar", "trim": 1500, "reverse": false},
    {"axis": 3, "channel": 8, "kind": "multi", "levels": 6,
     "values": [1000, 1200, 1400, 1600, 1800, 2000]}
  ],
  "buttons": [
    {"button": 2, "channel": 7, "low": 1000, "high": 2000, "toggle": false}
  ],
  "constants": {"9": 2000},
  "keyboard": {
    "enabled": true,
    "source": "auto",
    "foreground_only": true,
    "window_process": "X-Plane.exe"
  }
}
```

| 字段 | 说明 |
|---|---|
| `host` / `port` | SITL 的 RC UART，默认 `127.0.0.1:5762` |
| `rate_hz` | RC 帧率，默认 50 Hz |
| `axes[].axis` | pygame/SDL 轴编号，用 `--list` 或 `hidctl setup` 确认 |
| `axes[].channel` | 目标 RC 通道（1–16） |
| `axes[].kind` | `bipolar`（双向）、`unipolar`（单向）、`tri`（三档）、`binary`（二值）、`multi`（多档） |
| `axes[].trim` | 中位/低端 PWM |
| `axes[].reverse` | 反向 |
| `axes[].deadband` / `expo` | 死区/曲线 |
| `axes[].threshold` | `tri`/`binary` 的切换阈值 |
| `axes[].levels` / `values` | `multi` 的档位数和每档 PWM |
| `buttons[].button` / `channel` | 按键编号 / 目标通道 |
| `buttons[].low` / `high` | 松开/按下（或开关低/高）的 PWM |
| `buttons[].toggle` | `true` 按一下切换，`false` 跟随开关状态 |
| `constants` | 固定通道值，CH9=2000 即 NAV LAUNCH |
| `keyboard.enabled` / `source` | 是否启用键盘；`auto` / `hid` / `keyboard` |
| `keyboard.foreground_only` | 只在前台进程匹配时响应，默认 `true` |
| `keyboard.window_process` | 前台进程名，默认 `X-Plane.exe` |
| `keyboard.axis_rate` / `throttle_rate` | 轴/油门变化速率（PWM/秒） |
| `keyboard.keys` | 动作 → 键名；支持 `ctrl+shift+space` 这类组合 |

`channel_map` 和 `mode_table` 只是给人看的文档字段，程序会忽略。

### 4.5 HID 设置向导（重新标定轴和方向）

同一只手柄在 macOS 和 Windows 上 SDL 的轴编号可能不同，换机器或换手柄后建议跑一次：

```powershell
.\hidctl.cmd setup
```

向导会依次要求（每一步按 Enter 后采样约 2 秒）：

| 步骤 | 操作 | 检测内容 |
|---|---|---|
| CH1 Roll | 回中 → 向右打满 | 轴号 + 方向 |
| CH2 Pitch | 回中 → 向上打满 | 轴号 + 方向 |
| CH3 Throttle | 最低 → 最高 | 轴号 + 方向 |
| CH4 Yaw | 回中 → 向右打满 | 轴号 + 方向 |
| CH8/CH5 | 旋钮最低档 → 最高档 | 轴号 + 六档方向 |
| CH6 SWC | 低位 → 高位 | 按键号 + 高电平极性 |
| CH7 SWB | 低位 → 高位 | 按键号 + 高电平极性 |

结束后会更新 `config\hid2msp_inav.json`，旧文件备份为
`config\hid2msp_inav.json.bak`，并打印每个通道最终使用的 `axis`/`button`
和 `reverse` 方向。

> Pitch 的方向判定和其它通道相反：向导按"拉杆（pitch up）时 CH2 应变低"来判断，
> 所以副翼向右、油门向上、偏航向右都是"打满时 PWM 变大"，pitch 则是"拉满时 PWM 变小"。

```powershell
.\hidctl.cmd setup --no-write    # 只看结果，不写文件
.\hidctl.cmd setup --restart     # 写完自动重启 bridge
```

某个通道检测不到明显变化时会重试 3 次；请确保只动向导要求的那一个摇杆/开关。
中途 Ctrl-C 不会写入任何内容。

如果向导完成后发现某个通道方向反了，不用重跑向导，直接翻转该通道：

```powershell
.\hidctl.cmd invert 2 --restart     # 翻转 CH2 Pitch
```

（`invert` 会切换该通道的 `reverse`，可加 `--restart` 立即让桥生效。）

> 跑向导前建议先 `.\hidctl.cmd stop bridge`：向导会要求拨动 SWB，
> 而桥如果还在运行会把 SWB 当作解锁信号。向导结束后再
> `.\hidctl.cmd start bridge`（或加 `--restart`）。

---

## 5. SITL 配置

SITL 启动时**只读** `config\runtime\plane.bin`（eeprom）。
人可读的源文件是 [config/INAV_SITL_MINIMAL_NODEFAULTS.txt](config/INAV_SITL_MINIMAL_NODEFAULTS.txt)，
必须加载并 `save` 才会写进 `plane.bin`。

首次使用或 `plane.bin` 丢失时，SITL 会生成一份**默认配置**（不是本项目配置），
需要加载一次。有两种方式：

### 5.1 自动加载（推荐）

```powershell
.\hidctl.cmd start sitl
.\hidctl.cmd config load
```

`config load` 会通过 TCP 5760 发送 `#` 进入 INAV CLI，把
`config\INAV_SITL_MINIMAL_NODEFAULTS.txt` 里的命令逐条送到飞控，最后 `save`，
并等待 SITL 重启、端口重新监听。

- 默认端口 5760。**Configurator 正连着 5760 时请先 Disconnect**（每个 UART 只允许一个客户端）；
  或者改用空闲的 UART，例如 `.\hidctl.cmd config load --port 5761`。
- `--file <path>` 换配置文件；`--no-save` 只发送不保存。
- 结束会打印错误行数量；像 `#wp 0 invalid` 这种来自 `diff all` 的注释行会被忽略。

### 5.2 手动加载（Configurator CLI）

1. Configurator 连 `127.0.0.1:5760`；
2. 打开 CLI；
3. 粘贴 `config\INAV_SITL_MINIMAL_NODEFAULTS.txt` 的全部内容；
4. 执行 `save`；
5. SITL 重启后重新连接 Configurator，插件重新 `Connect to SITL`。

改配置前建议先备份：

```powershell
.\hidctl.cmd backup eeprom --name before-fc-change
```

> 本机验证使用的是 **INAV SITL 10.0.0**（Configurator 10.0.0 自带）：
> 302 条命令加载完成、`save` 后 UART3(5762)/UART4(5763) 正常监听，
> 桥接器发出的通道在 `MSP_RC` 中可见。eeprom 与 SITL 版本相关，
> 换 Configurator 版本后建议重新加载一次。

### 5.3 备份 / 恢复 / 重置

```powershell
.\hidctl.cmd backup eeprom [--name 标签]
.\hidctl.cmd backups
.\hidctl.cmd restore eeprom config\runtime\backups\plane-20261110-151844.bin --yes
.\hidctl.cmd reset eeprom --yes
```

`restore` 会先停组件、默认再备份当前 eeprom，然后覆盖并启动；
`reset` 删除 eeprom，让 SITL 生成全新默认配置（只启动 SITL）。

### 5.4 UART 与 aux（关键 CLI 字段）

CLI 的 `serial` id 从 **0** 开始，对应关系不能写错：

```text
serial 0 = UART1 = 5760 Configurator
serial 1 = UART2 = 5761 HITL 插件
serial 2 = UART3 = 5762 手柄桥
serial 3 = UART4 = 5763 MSP DisplayPort
```

源配置里的核心设置：

```text
set receiver_type = MSP
set gps_provider = FAKE
set acc_hardware = FAKE
set baro_hardware = FAKE
set mag_hardware = FAKE
set pitot_hardware = FAKE
set rssi_source = NONE
set osd_video_system = AVATAR

aux 0 0 2 1950 2050   # CH7 SWB -> ARM
aux 1 1 3 950 1050    # CH8 1000 -> ANGLE
aux 2 2 3 1150 1250   # CH8 1200 -> HORIZON
aux 3 12 3 1350 1450  # CH8 1400 -> MANUAL
aux 4 53 3 1550 1650  # CH8 1600 -> NAV CRUISE
aux 5 11 3 1750 1850  # CH8 1800 -> NAV POSHOLD
aux 6 10 3 1950 2050  # CH8 2000 -> NAV RTH
aux 7 36 4 1950 2050  # CH9 2000 -> NAV LAUNCH
aux 8 28 1 1950 2050  # CH6 SWC -> NAV WP
```

`aux` 的第 3 个参数是 **0 基通道号**：`2` = CH7、`3` = CH8、`4` = CH9、`1` = CH6。
模式编号是 INAV 的 permanent ID：

| ID | 模式 | ID | 模式 |
|---|---|---|---|
| 0 | ARM | 1 | ANGLE |
| 2 | HORIZON | 12 | MANUAL |
| 53 | NAV CRUISE | 11 | NAV POSHOLD |
| 10 | NAV RTH | 36 | NAV LAUNCH |
| 28 | NAV WP | | |

### 5.5 eeprom 与源文件的关系

```text
config\INAV_SITL_MINIMAL_NODEFAULTS.txt   人可读的 CLI 源文件
        │  只在 Configurator CLI 或 hidctl config load 时手动加载
        ▼
config\runtime\plane.bin                  32 KB 飞控 eeprom
        │  SITL 每次启动用 --path 读取
        ▼
INAV SITL 运行时配置
```

- 改 `.txt` **不会**自动影响正在运行的 SITL；必须 `config load` 或手动加载并 `save`；
- `hidctl` 只把 `plane.bin` 传给 SITL，不读 `.txt`；
- `plane.bin` 不存在时 SITL 会生成默认配置，需要加载一次；
- 不要直接编辑 `plane.bin`（二进制），用 Configurator/CLI 修改后 `save`；
- 要让仓库可复现，改完后在 CLI 执行 `diff all`，把输出更新到
  `config\INAV_SITL_MINIMAL_NODEFAULTS.txt` 并提交。

---

## 6. 目录、文件与配置分类

```text
Joystick-for-iNav-XPlane11-SITL\
├─ hidctl.cmd / hidctl.py       统一入口：启停、状态、日志、备份、恢复、配置加载
├─ scripts\                     桥、键盘、标定、日志泵、MSP 调试工具
├─ config\
│  ├─ hid2msp_inav.json         当前 HID/键盘映射（实际使用）
│  ├─ hid2msp.example.json      通用 Xbox 风格示例（仅参考）
│  ├─ INAV_SITL_MINIMAL_NODEFAULTS.txt  SITL CLI 源配置
│  ├─ calibration.json          可选标定结果（忽略）
│  └─ runtime\
│     ├─ plane.bin              SITL 每次启动读取的 eeprom
│     └─ backups\               eeprom 备份（忽略）
├─ run\                         PID、hidctl.lock（忽略）
├─ logs\                        sitl/bridge/hidctl/observe/capture（忽略）
├─ 3rdparty\                    INAV/HITL 源码参考（不参与运行，忽略）
└─ docs\                        历史文档与图
```

| 分类 | 文件 | 谁读取 | 作用 |
|---|---|---|---|
| SITL 运行时配置 | `config\runtime\plane.bin` | SITL 每次启动 | 真正的飞控 eeprom |
| SITL 源配置 | `config\INAV_SITL_MINIMAL_NODEFAULTS.txt` | 人/Configurator CLI | 可读写的 CLI 源文件，加载后生效 |
| HID 映射 | `config\hid2msp_inav.json` | `hid2msp.py` | 轴/按键/键盘 → CH1–CH9 |
| 标定结果 | `config\calibration.json` | 人/`calibrate_hid.py` | 可选，忽略 |
| 运行状态 | `run\*.pid`、`run\hidctl.lock` | `hidctl` | 进程管理与互斥 |
| 日志 | `logs\` | 人 | 排错、MSP 抓包、观察记录 |

> `config\runtime\`、`run\`、`logs\` 都是运行时目录，已被 `.gitignore` 排除。
> 不要直接编辑 `plane.bin`。

---

## 7. 用 Configurator 配置 SITL

Configurator 连接 **TCP `127.0.0.1:5760`**。

### 7.1 Receiver

- Receiver type：**MSP**
- 不要选 `SIM (SITL)`（那是 X-Plane 原生摇杆，不走 `hid2msp.py`）
- 不要选 `SERIAL`，除非你接真实串口接收机

### 7.2 Ports

| UART | 功能 | TCP 端口 |
|---|---|---|
| UART1 | MSP | 5760 |
| UART2 | MSP | 5761 |
| UART3 | MSP | 5762 |
| UART4 | MSP DisplayPort | 5763 |

CLI 的 `serial` id 从 0 开始：`serial 0`=UART1、`serial 1`=UART2、`serial 2`=UART3、`serial 3`=UART4。

### 7.3 Mixer

- Platform：**AIRPLANE**
- 当前配置保留双发固定翼 mixer（`model_preview_type = 26`）
- HITL 插件只使用 roll/pitch/yaw/throttle 四个控制量，不逐个读取舵机输出
- 不要在 SITL 里选 Flying Wing 再期待 X-Plane 看到左右 elevon

### 7.4 Sensors

| 项目 | 设置 |
|---|---|
| Accelerometer / Barometer / Magnetometer / Pitot | `FAKE` |
| Rangefinder / Optical flow | `NONE` |
| GPS | `FAKE` |

`ins_gravity_cmss` 等真机校准值 SITL 不需要，精简配置里已移除。

### 7.5 OSD

- Configuration → Other features：勾选 `OSD`
- OSD → Video system：`AVATAR`（也支持 `HDZERO`、`DJIWTF`、`BF43COMPAT`）
- Ports → UART4：`MSP DisplayPort`

SITL 没有模拟 MAX7456，必须走 **MSP DisplayPort + HD OSD**，否则插件会提示
`SUPPORTED OSD TYPE NOT FOUND`。UART4 不直接给 X-Plane 送画面，插件通过 5761 读取 OSD 内容并绘制。

**Glide Range / Glide Time 必须保持隐藏**，否则 INAV 10 会 SIGFPE（见 9.5）。

### 7.6 Modes

| 通道 | 作用 |
|---|---|
| CH6 | SWC → NAV WP（高=开） |
| CH7 | SWB → ARM（高=解锁） |
| CH8 | 旋钮六段模式 |
| CH9 | 常高 → NAV LAUNCH |

AUX 表丢失时，重新加载 `config\INAV_SITL_MINIMAL_NODEFAULTS.txt`。

### 7.7 加载 CLI 配置

1. Configurator 连 `127.0.0.1:5760`；
2. 打开 CLI；
3. 粘贴 `config\INAV_SITL_MINIMAL_NODEFAULTS.txt` 的全部内容；
4. 执行 `save`；
5. SITL 重启后重新连接 Configurator，插件重新 `Connect to SITL`。

或者直接用：

```powershell
.\hidctl.cmd config load
```

从非全新 eeprom 恢复时，先 `.\hidctl.cmd backup eeprom`；遇到 SITL 崩溃时，
删除/替换 eeprom 让 SITL 生成全新配置，再加载 CLI。

### 7.8 保存流程（RAM → eeprom → Git）

| 层次 | 操作 | 结果 |
|---|---|---|
| RAM | 在 Configurator 里改参数 | 只对当前 SITL 有效，重启丢失 |
| eeprom | 点 Save，或 CLI `save` | 写入 `plane.bin`，下次启动继续使用 |
| Git | `diff all` → 更新 `.txt` → commit | 仓库可复现，不会自动发生 |

保存后 SITL 会重启，5760–5763 短暂断开再恢复；bridge 会自动重连，插件需要重新 Connect。
确认参数无误后再备份一份：

```powershell
.\hidctl.cmd backup eeprom --name after-fc-change
```

---

## 8. 操作流程

### 8.1 解锁

1. 油门最低；
2. 左右摇杆回中；
3. SWB 拨到高位；
4. Configurator 的 Receiver 页确认 **CH7 = 2000**；
5. 解锁。

如果 SWB 高位时 CH7 还是 1000，检查 JSON 里的 `low`/`high` 是否对调。
键盘模式用 `Ctrl+A` 切换解锁，油门 > 1050 会拒绝。

### 8.2 模式选择

- 旋钮：CH8 六档（ANGLE / HORIZON / MANUAL / CRUISE / POSHOLD / RTH）；
- SWC 高：叠加 NAV WP；
- CH9 常高：NAV LAUNCH 永久启用。

### 8.3 失控保护

- INAV `failsafe_procedure = RTH`；
- `hid2msp.py` 停止/崩溃后，SITL 约 200 ms 收不到 RC 帧，进入 failsafe；
- 地面测试：解锁前先停掉 bridge，观察 Configurator/OSD 是否进入 FS；测试完再启动 bridge。

---

## 9. 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `couldn't create signal pipe, Win32 error 5` | INAV SITL 是 Cygwin 程序，需要创建命名管道；受限沙箱/无桌面会话里会被拒绝 | 在普通 PowerShell 窗口里运行 `hidctl.cmd`；不要在受限沙箱中启动 SITL |
| `SITL not found` | 没装 Configurator 或路径不同 | 设 `HIDCTL_SITL` 指向 `inav_SITL.exe` |
| `SITL ports already in use` | 旧 SITL 没退 | `.\hidctl.cmd stop`，再用 `netstat -ano | findstr 5760` 确认 |
| `bridge exited immediately` | pygame 缺失且键盘不可用，或配置错误 | 看 `logs\bridge.log`；`.\hidctl.cmd doctor` |
| 键盘没反应 | X-Plane 不是前台窗口（`foreground_only`），或焦点在管理员权限的程序上 | 把 X-Plane 切到前台；必要时用普通权限运行 |
| 提示 `another hidctl operation is in progress` | 上次 hidctl 被关闭，`run\hidctl.lock` 残留 | `.\hidctl.cmd unlock`；新版会按锁里的 PID 自动清理已经退出的进程 |
| 手柄没反应 | 没装 pygame，或轴编号不同 | `python scripts\hid2msp.py --list` 看轴/按键编号，再改 JSON |
| HITL 菜单不出现 | 没加载 INAV Surfwing（插件是 Aircraft 插件） | 加载该机型；勾选 `Show extra aircraft from old versions` |
| `unable to arm no rc link` | bridge 没运行或没连上 5762 | `.\hidctl.cmd status`；`.\hidctl.cmd start bridge` |
| `SUPPORTED OSD TYPE NOT FOUND` | 没有 MSP DisplayPort / HD OSD | UART4 设 `MSP DisplayPort`，OSD video `AVATAR` |
| SITL 版本不匹配 | eeprom 与当前 SITL 版本不一致 | 用当前版本重新生成 eeprom 并加载 CLI；必要时切回对应 Configurator |

`doctor` 会逐项检查：SITL 二进制、X-Plane、HITL 插件、Python、桥脚本、
pygame/手柄、键盘、HID 配置、eeprom、四个端口。

### 9.1 SITL 在 Windows 上“莫名其妙死掉”

`inav_SITL.exe` 是控制台程序。如果它附着在启动它的终端/控制台上，**关闭那个窗口**
时 Windows 会给它发 `CTRL_CLOSE_EVENT`，Cygwin 转成 SIGHUP，进程以
`0xC000013A`（STATUS_CONTROL_C_EXIT）退出。这个退出不经过 `hidctl stop`，
所以 `logs\sitl.log` 没有 `stop sitl` 记录，事件查看器也没有崩溃报告，
看起来就像“莫名其妙消失”。

实测：用 `CREATE_NEW_CONSOLE` 启动 SITL，再向它的控制台窗口发 `WM_CLOSE`，
进程立刻以 `3221225786`（0xC000013A）退出；同一时刻脱离控制台的实例不受影响。

macOS 分支用 `start_new_session=True`（setsid）脱离终端；Windows 分支现在用
`DETACHED_PROCESS`（失败时回退到 `CREATE_NEW_PROCESS_GROUP`），SITL 和 bridge
都不再附着控制台：

- 关掉 PowerShell 窗口、IDE 终端、SSH 会话都不影响 SITL/bridge；
- `hidctl status` 仍用 PID 文件管理它们；
- `hidctl stop` 对无控制台的进程走 `taskkill /T /F`；
- 想重启栈请用 `hidctl restart`，不要靠关窗口。

如果以后还看到 SITL 消失，先看 `logs\sitl.log` 有没有 `stop sitl` 头：
有就是 hidctl 停的，没有就是外部原因（控制台关闭、被任务管理器结束、崩溃）。

### 9.2 多终端与重复进程

`run\*.pid`、`logs\` 都在仓库目录里，同一份仓库的多个终端共享：

- **终端 A 的 `hidctl status` 能看到终端 B 用 `hidctl` 起的 SITL/bridge**，
  因为读的是同一份 PID 文件；
- `start` 是幂等的，已经在运行就直接返回；
- 启动 SITL 前会检查 **任何 `inav_SITL.exe` 进程**（不只看端口），
  启动 bridge 前会检查 **5762 上已连接的 Python 客户端**，
  所以就算 PID 文件丢了也不会重复起第二份；
- 不由 `hidctl` 启动的进程（手工运行、另一个仓库副本、Configurator 拉起的 SITL）
  会在 `status` 里显示为 `stray`：

  ```text
  stray   pid 2212  inav_SITL.exe  (inav_SITL not managed by this hidctl)
  stray   pid 4820  python3.12.exe (connected to 5762, not managed by this hidctl)
  ```

  此时 `start` 会拒绝启动并提示先停掉这些进程。

PID 文件现在记录 **PID + 进程创建时间**（`run\sitl.pid` 两行）；PID 被系统复用时
创建时间对不上，`status`/`stop` 不会把无关进程当成 SITL/bridge，避免误杀。

清理 `stray` 进程：在任务管理器里结束，或 `taskkill /PID <pid> /T /F`。

### 9.3 日志格式

所有组件日志现在**逐行带时间戳**，由 [scripts/logpump.py](scripts/logpump.py) 管道写入：

```text
2026-11-10 23:36:10 [SOCKET] [::ffff:127.0.0.1]:5927 connected to UART1
```

- SITL/bridge 的 stdout 由 logpump 加时间戳后写进 `logs\sitl.log`、`logs\bridge.log`；
- 进程退出时会追加一行退出码，例如：

  ```text
  2026-11-10 23:44:01 ===== inav_SITL.exe exited code=2048 (0x00000800) =====
  ```

  这条是排查“莫名其妙死掉”的关键，不再需要外部监控；
- logpump 同时维护 `run\sitl.pid` / `run\bridge.pid`，进程退出时删除。

`logs\hidctl.log` 是 **hidctl 自己的操作日志**：每条命令、spawn/stop、`config load`、
`setup`、`invert`、`backup/restore/reset` 和错误都会记录时间戳：

```powershell
.\hidctl.cmd logs hidctl -n 20
.\hidctl.cmd logs all -f
```

### 9.4 MSP 调试工具

**1. 读飞控状态（不开 Configurator）**

```powershell
python scripts\msp_probe.py --port 5760
python scripts\msp_probe.py --port 5760 --watch     # 每秒打印 RC + 姿态
python scripts\msp_probe.py --port 5762 --rc 1500,1500,1000,1500 --count 50
```

输出 `api_version`、`fc_version`、`status`（mode flags）、`rc`、`attitude`、`box_ids`、
`mode_ranges`。注意每个 UART 同时只允许一个客户端：Configurator 占着 5760、
插件占着 5761 时，探针要换端口或先断开它们。

**2. 抓插件 → 飞控的 MSP 流量**

HITL 插件固定连 `127.0.0.1:5761`，所以用一个用户态 TCP tap 最方便（不需要管理员、
不需要装 pcap 驱动）：

```powershell
.\hidctl.cmd stop
.\hidctl.cmd capture --seconds 180
```

`capture` 会临时启动：
- SITL：`5860-5863`（副本端口，不碰正常的 5760）；
- tap：`5761 -> 5861`，把插件的每一帧 MSP 写进 `logs\capture\msp-*.log`；
- bridge：`5862`。

然后按提示在 X-Plane 里 `Connect to SITL → 127.0.0.1:5761` 即可。结束会打印
MSP 帧数；日志里能看到 `MSP_SET_RAW_RC` 的通道值、`MSP_SIMULATOR` 等命令和时间戳。

> 为什么不用 `pktmon`：它需要管理员权限，而且 **抓不到 127.0.0.1 回环流量**
> （NDIS 层看不到 loopback），所以这里用用户态 tap。`scripts\msp_tap.py` 也可以单独运行。

### 9.5 已知问题：Glide Range / Glide Time 导致 SITL 退出（INAV 10）

**现象**：解锁后，或飞行中打开 Glide Range，SITL 无声退出，`logs\sitl.log` 里是：

```text
===== inav_SITL.exe exited code=2048 (0x00000800) =====   ← SIGFPE
```

X-Plane 插件随即断联。关闭 OSD 后可以稳定飞行；只隐藏这两个元素也能正常解锁。

**原因**：INAV 10 `src/main/io/osd.c` 的 `osdGetRemainingGlideTime()`：

```c
float value = getEstimatedActualVelocity(Z);
...
if (value < 0) {
    value = osdGetAltitude() / abs((int)value);   // (int)value == 0 时整数除零
}
```

垂直速度落在 **-1 ~ 0 cm/s** 时 `(int)value == 0`，`abs(0) == 0`，触发 SIGFPE。

**触发元素**：

| 元素 | 编号 |
|---|---|
| `OSD_GLIDE_RANGE` | 137 |
| `OSD_GLIDE_TIME_REMAINING` | 136 |

**处理**（`H` 隐藏、`V` 显示）：

```text
osd_layout 0 137 46 3 H
osd_layout 0 136 14 9 H
save
```

Configurator 的 OSD 页面取消勾选 **Glide Range** / **Glide Time Remaining** 效果相同。

**验证记录**：

- OSD 关闭 + 解锁：120 秒稳定；
- OSD 打开：解锁后约 11 秒 SIGFPE；
- 只关闭 137/136、其余 OSD 全开：可以解锁并正常飞行（实测）。

这是 INAV 10 固件的 bug，不是 HITL 插件或 bridge 的问题；升级 INAV 后可以再打开这两个元素。

---

## 10. 安全与限制

- 这是**仿真环境**，但 `NAV LAUNCH` 永久启用（CH9 常高），SITL 里解锁就会进入起飞模式；
  解锁前确认模型/桨叶周围无人。
- `config\INAV_SITL_MINIMAL_NODEFAULTS.txt` 只是 SITL 配置，**不要刷入真实飞机**。
- HITL 插件只支持固定翼，只回传 roll/pitch/yaw/throttle 四个控制量；
  INAV 的每个舵机混控不会逐个出现在 X-Plane，Flying Wing/elevon 不要指望在 X-Plane 里看到。
- SITL 没有模拟 MAX7456，OSD 必须走 MSP DisplayPort + HD OSD。
- HITL 插件 v1.5.0 主要面向 INAV 7/8；INAV 10 联调可能有协议差异。
  当前已知 INAV 10 的 Glide Range/Glide Time 会 SIGFPE，必须保持隐藏（见 9.5）。
- 键盘默认只在 X-Plane 前台时生效；这不是安全认证，只是避免误触。
- 配置里的 PID、OSD、导航参数是仿真调参，未经真机验证；真机使用前必须重新检查
  传感器校准、failsafe、arm 开关方向、模式优先级、电机/舵机方向。

---

## 11. FAQ

**Q：为什么键盘在浏览器里没反应？**

A：默认 `foreground_only = true`，只有 X-Plane 前台才响应。想全局响应就设
`"foreground_only": false`，但不推荐。

**Q：怎么把解锁设成组合键？**

A：`.\hidctl.cmd setup keyboard`，在 `Arm / disarm` 步骤按住 `Ctrl+Shift` 再按 `Space`，
得到 `ctrl+shift+space`；也可以直接改 `keyboard.keys.arm`。

**Q：手柄和键盘谁优先？**

A：`keyboard.source`：`auto` 有手柄用手柄，否则键盘；`hid` 强制手柄；`keyboard` 强制键盘。

**Q：Configurator 连不上 5760？**

A：每个 UART 只允许一个客户端。先断开其他 Configurator/CLI 会话；
`hidctl config load` 也会占用 5760，用完会释放。

**Q：SITL 为什么无声退出？**

A：先看 `logs\sitl.log` 的退出码。`0x800` 是 SIGFPE，常见原因是 Glide Range/Glide Time
（见 9.5）；没有退出码则看是否被关窗口/任务管理器结束。

**Q：OSD 提示 `SUPPORTED OSD TYPE NOT FOUND` 或 `OSD IS DISABLED`？**

A：确认 Other features 里 OSD 打开、Video system = AVATAR、UART4 = MSP DisplayPort；
Glide 元素保持隐藏。

**Q：怎么恢复一份干净配置？**

A：`.\hidctl.cmd backup eeprom --name before` → `.\hidctl.cmd reset eeprom --yes` →
`.\hidctl.cmd start sitl` → `.\hidctl.cmd config load`。

**Q：这套配置能直接上真机吗？**

A：不能。它只用于 SITL；真机需要重新做传感器校准、舵机方向、failsafe 和 PID 验证。

---

## 12. 与 main（macOS）分支的差异

| 方面 | main | windows |
|---|---|---|
| 入口 | `./hidctl`（无扩展名、可执行位） | `hidctl.cmd` + `hidctl.py` |
| 进程管理 | `lsof` / `pgrep` / `killpg` / `SIGKILL` | `OpenProcess` / `QueryFullProcessImageNameW` / `taskkill` / `CTRL_BREAK` |
| 后台方式 | `start_new_session=True`（setsid） | `DETACHED_PROCESS`，不附着控制台 |
| 存活探测 | `os.kill(pid, 0)` | `GetExitCodeProcess`（Windows 上 `os.kill` 会直接杀进程） |
| 端口连接 | `lsof -iTCP` | `netstat -ano` |
| X-Plane 探测 | `.app` + `Info.plist` + `pgrep` | 注册表 Steam 路径 + `tasklist` + 版本资源 |
| 插件路径 | `mac.xpl` | `win.xpl` |
| 键盘 | CoreGraphics + 输入监控权限 | `GetAsyncKeyState`，默认仅 X-Plane 前台，支持组合键 |
| 日志跟随 | `tail -f` | Python 轮询 |
| 依赖目录 | 无 | 可选 `.deps\`（pygame） |

---

## 13. 参考

- INAV SITL：<https://github.com/iNavFlight/inav/blob/master/docs/SITL/SITL.md>
- INAV X-Plane：<https://github.com/iNavFlight/inav/blob/master/docs/SITL/X-Plane.md>
- INAV-X-Plane-HITL：<https://github.com/RomanLut/INAV-X-Plane-HITL>
- pygame：<https://www.pygame.org/>
- macOS 方案调研（历史）：[docs/README-macos.md](docs/README-macos.md)、[docs/SOLUTION.md](docs/SOLUTION.md)
