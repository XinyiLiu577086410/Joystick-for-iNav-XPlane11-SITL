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

四个 TCP 端口全在本机，每个 UART 同时只允许一个客户端：

| 端口 | UART | 客户端 | 协议 |
|---|---|---|---|
| 5760 | UART1 | INAV Configurator | MSP 配置 / CLI |
| 5761 | UART2 | X-Plane HITL 插件 | `MSP_SIMULATOR` |
| 5762 | UART3 | `hid2msp.py` | `MSP_SET_RAW_RC` |
| 5763 | UART4 | 无（SITL 自用） | MSP DisplayPort / HD OSD |

---

## 2. 依赖

| 组件 | 要求 | 检查 |
|---|---|---|
| Windows | 10 / 11，64 位 | — |
| Python | 3.10+ | `python --version` |
| INAV Configurator | 9.x（自带 `inav_SITL.exe`） | `hidctl.cmd doctor` |
| X-Plane | 11.55+ 或 12 | `hidctl.cmd doctor` |
| HITL 插件 | v1.5.0（已装到 `NK_FPVSurfwing`） | `hidctl.cmd status` |
| pygame | 仅手柄模式需要 | `python -m pip install pygame` |

键盘模式**不需要** pygame，也不需要任何额外权限；Windows 用
`GetAsyncKeyState` 全局读键，不需要窗口焦点。

### 2.1 安装 HITL 插件（如果还没装）

```powershell
git clone https://github.com/RomanLut/INAV-X-Plane-HITL.git 3rdparty\INAV-X-Plane-HITL
Copy-Item "3rdparty\INAV-X-Plane-HITL\release\Aircraft\Extra Aircraft\NK_FPVSurfwing" `
          "C:\Program Files (x86)\Steam\steamapps\common\X-Plane 11\Aircraft\Extra Aircraft\" -Recurse
```

Steam 装在别处时，把目标路径换成实际的 `X-Plane 11` 目录。

### 2.2 pygame

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
sitl    running  pid 5752  ports 5760,5761
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

当前配置见 [config/hid2msp_inav.json](config/hid2msp_inav.json)：

| 通道 | 功能 | 来源 |
|---|---|---|
| CH1 | Roll | 手柄 axis 5 |
| CH2 | Pitch | axis 0 |
| CH3 | Throttle | axis 1 |
| CH4 | Yaw | axis 4 |
| CH5 | 旋钮三档原始指示 | axis 3，`tri` |
| CH6 | SWC → NAV WP | button 3，高=开 |
| CH7 | SWB → ARM | button 2，高=解锁 |
| CH8 | 六段模式 | axis 3，`multi` 6 档 |
| CH9 | NAV LAUNCH | 常量 2000 |

六段模式：

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

### 4.1 键盘控制（无手柄时自动启用）

键盘输入只在 **X-Plane 是当前最上层窗口** 时生效；切到浏览器、终端或其他软件时，
按键会被忽略，摇杆自动回中、油门保持、解锁状态不变，不会误触。

| 键 | 功能 |
|---|---|
| `W` / `S` | Pitch 上 / 下 |
| `A` / `D` | Roll 左 / 右 |
| `Q` / `E` | Yaw 左 / 右 |
| `1`–`6` | 六段模式：ANGLE / HORIZON / MANUAL / CRUISE / POSHOLD / RTH |
| `Space` | 按一下切换解锁/上锁 |
| `Left Shift` | 按住增加油门 |
| `Left Control` | 按住减少油门 |

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

### 4.2 设置向导（重新标定轴和方向）

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

---

## 6. 排错

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
| SITL 版本不匹配 | 本机是 9.1.0，项目原配置来自 9.0.0 | 用 9.1.0 重新生成 eeprom 并加载 CLI；必要时装 Configurator 9.0.0 |

`doctor` 会逐项检查：SITL 二进制、X-Plane、HITL 插件、Python、桥脚本、
pygame/手柄、键盘、HID 配置、eeprom、四个端口。

### 6.1 SITL 在 Windows 上“莫名其妙死掉”

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

### 6.2 多终端与重复进程

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

### 6.3 日志格式

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

### 6.4 MSP 调试工具

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

### 6.5 已知问题：Glide Range / Glide Time 导致 SITL 退出（INAV 10）

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

## 7. 与 main（macOS）分支的差异

| 方面 | main | windows |
|---|---|---|
| 入口 | `./hidctl`（无扩展名、可执行位） | `hidctl.cmd` + `hidctl.py` |
| 进程管理 | `lsof` / `pgrep` / `killpg` / `SIGKILL` | `OpenProcess` / `QueryFullProcessImageNameW` / `taskkill` / `CTRL_BREAK` |
| 后台方式 | `start_new_session=True`（setsid） | `DETACHED_PROCESS`，不附着控制台 |
| 存活探测 | `os.kill(pid, 0)` | `GetExitCodeProcess`（Windows 上 `os.kill` 会直接杀进程） |
| 端口连接 | `lsof -iTCP` | `netstat -ano` |
| X-Plane 探测 | `.app` + `Info.plist` + `pgrep` | 注册表 Steam 路径 + `tasklist` + 版本资源 |
| 插件路径 | `mac.xpl` | `win.xpl` |
| 键盘 | CoreGraphics + 输入监控权限 | `GetAsyncKeyState`，无需权限 |
| 日志跟随 | `tail -f` | Python 轮询 |
| 依赖目录 | 无 | 可选 `.deps\`（pygame） |

---

## 8. 参考

- INAV SITL：<https://github.com/iNavFlight/inav/blob/master/docs/SITL/SITL.md>
- INAV X-Plane：<https://github.com/iNavFlight/inav/blob/master/docs/SITL/X-Plane.md>
- INAV-X-Plane-HITL：<https://github.com/RomanLut/INAV-X-Plane-HITL>
- pygame：<https://www.pygame.org/>
- macOS 方案调研（历史）：[docs/README-macos.md](docs/README-macos.md)、[docs/SOLUTION.md](docs/SOLUTION.md)
