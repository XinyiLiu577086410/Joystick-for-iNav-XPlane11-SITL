# hid-as-rx

在 macOS 上用 **HID 手柄/遥控器** 当接收机，驱动 **INAV SITL**，并把 **X-Plane 11** 当作飞行仿真器。

这个项目不是给真机刷固件，而是一套 **SITL + HITL 桌面仿真环境**：

- X-Plane 提供飞机物理、画面和 OSD 显示；
- INAV SITL 提供真实的飞控逻辑（接收机、混控、PID、导航、模式）；
- HID 手柄/遥控器通过 `hid2msp.py` 变成 INAV 的 **MSP 接收机**；
- INAV Configurator 用来配置 SITL 里的“飞控”。

> 当前验证环境：macOS 26.3.1 arm64、X-Plane 11.55r2（Steam）、INAV Configurator 9.0.0、INAV SITL 9.0.0、Python 3.10 + pygame 2.1.2。

---

## 0. 最快启动

```bash
cd "$HOME/Desktop/Read-the-Source-Code/hid-as-rx"

# 终端 A：SITL
./start_sitl.sh

# 终端 B：手柄桥（先把 SWB 拨到低位）
./start_bridge.sh

# 检查端口
./check_ports.sh
```

然后：

1. X-Plane 11 加载 **INAV Surfwing**；
2. `Plugins → INAV HITL/SITL → Connect to SITL → 127.0.0.1:5761`；
3. 需要改参数时，Configurator 用 **TCP 127.0.0.1:5760** 连接。

更详细的安装、配置和排错见下文。

---

## 1. 系统组成

### 1.1 必须安装/准备的组件

| 组件 | 版本/位置 | 作用 | 是否必须 |
|---|---|---|---|
| **macOS** | 13+，本项目在 26.3.1 验证 | 宿主系统 | 是 |
| **X-Plane 11** | 11.55r2，Steam 版 | 飞机物理、渲染、HITL 插件宿主 | 是 |
| **INAV Configurator** | 9.0.0 | 配置 SITL；自带 macOS SITL 二进制 | 是 |
| **INAV SITL** | 9.0.0，Configurator 内置 | 运行飞控逻辑 | 是 |
| **INAV HITL 插件 + INAV Surfwing** | `INAV-X-Plane-HITL/release/` | 把 X-Plane 传感器/控制/OSD 接到 SITL | 是 |
| **Python 3** | 3.10+ | 运行 `hid2msp.py` 和标定脚本 | 是 |
| **pygame** | 2.x | 读取 HID 手柄/遥控器 | 是 |
| **HID 手柄/遥控器** | USB HID | 提供 AETR、旋钮、开关 | 是 |
| **INAV Configurator 的 SITL 二进制** | `.../Contents/Resources/sitl/macos/inav_SITL` | 实际运行的 SITL | 是 |

**不需要：**

- 不需要真实飞控；
- 不需要真实接收机；
- 不需要自己编译 SITL；
- 不需要自己编译 HITL 插件（用 release 里的 `mac.xpl`）；
- 不需要改真实飞机的 INAV 配置。

### 1.2 组件协作关系

![系统架构](docs/architecture.png)

![启动时序](docs/startup.png)

四个 TCP 服务都在本机：

| 端口 | SITL UART | 客户端 | 协议/用途 |
|---|---|---|---|
| `5760` | UART1 | INAV Configurator | MSP 配置、CLI |
| `5761` | UART2 | X-Plane HITL 插件 | `MSP_SIMULATOR`：传感器 + 控制 + OSD |
| `5762` | UART3 | `hid2msp.py` | `MSP_SET_RAW_RC`：RC 通道 |
| `5763` | UART4 | 无（SITL 自己输出） | MSP DisplayPort / HD OSD |

关键点：

- **每个 UART 同时只能有一个 TCP 客户端**，所以 Configurator、插件、手柄桥必须各占一个 UART。
- HID 手柄不是 X-Plane 的摇杆，而是通过 `hid2msp.py` 变成 INAV 的 MSP 接收机。
- X-Plane 里的飞机由 HITL 插件控制；插件把 SITL 的 roll/pitch/yaw/throttle 写进 X-Plane。
- OSD 由 HITL 插件绘制；SITL 用 UART4 的 MSP DisplayPort 维护 OSD 画布，插件通过 5761 的 MSP_SIMULATOR 读取并绘制。

### 1.3 运行时序

![运行时序](docs/sequence.png)

一次 50 Hz 的循环：

1. `hid2msp.py` 读取 HID 的轴/按键；
2. 通过 `5762` 发 `MSP_SET_RAW_RC`（CH1–CH9）；
3. SITL 做接收机解析、混控、PID、导航；
4. SITL 通过 `5761` 回 `MSP_SIMULATOR`（控制量、OSD、状态位）；
5. HITL 插件把控制量写进 X-Plane，并绘制 OSD；
6. X-Plane 把姿态/传感器数据回传给插件，插件再通过 MSP 回给 SITL。

---

## 2. 目录和文件

> 本仓库只包含 `hid-as-rx` 自己的代码、配置和文档；不包含三个上游源码仓库。首次使用请在同级目录单独准备：
>
> ```bash
> git clone https://github.com/RomanLut/INAV-X-Plane-HITL.git
> git clone https://github.com/iNavFlight/inav.git                  # 仅源码参考，可选
> git clone https://github.com/iNavFlight/inav-configurator.git     # 仅源码参考，可选
> ```
>
> 运行时真正需要的是 **INAV-X-Plane-HITL 的 `release/`** 和 **INAV Configurator 9.0.0 应用**。

### 2.1 配置文件分类

| 分类 | 文件/位置 | 谁读取 | 作用 |
|---|---|---|---|
| **SITL 运行时配置** | `.sitl/plane.bin` | SITL 每次启动读取 | 真正的飞控 eeprom，所有 `set/serial/aux/osd` 最终都在这里 |
| **SITL 源配置** | [XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt](XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt) | 人/Configurator CLI | 可读写的 CLI 源文件；加载进 eeprom 后才生效 |
| **HID 映射** | [hid2msp_xiaoweng.json](hid2msp_xiaoweng.json) | `hid2msp.py` 每次启动 | 轴/按键 → CH1–CH9、六段模式、CH9 常高 |
| **通用示例** | [hid2msp.example.json](hid2msp.example.json) | 仅参考 | Xbox 风格示例，不是当前配置 |
| **标定结果** | `calibration.json` | 人/`calibrate_hid.py` | 可选；脚本生成，已被 `.gitignore` 忽略 |
| **启动脚本** | [start_sitl.sh](start_sitl.sh)、[start_bridge.sh](start_bridge.sh)、[check_ports.sh](check_ports.sh) | 人 | 带起组件 |
| **文档/图** | `README.md`、`SOLUTION.md`、`docs/*.png` | 人 | 说明与架构/时序图 |
| **上游仓库** | `inav/`、`inav-configurator/`、`INAV-X-Plane-HITL/` | 不参与运行 | 本地参考；`.gitignore` 排除 |

已删除的旧文件（避免误用）：

- `XIAOWENG_SITL_6modes.txt`（旧 SWA 3×2 版本）
- `XIAOWENG_SITL_MINIMAL.txt`（带 `defaults noreboot` 的旧重载版本）
- `hid2msp_xiaoweng.example.json`（旧模板）
- `.sitl/*.log`、`.sitl/*.bak`、`.sitl/*.py`（开发调试产物）

### 2.2 文件清单

| 文件 | 作用 |
|---|---|
| [README.md](README.md) | 本文件：安装、启动、配置、排错 |
| [SOLUTION.md](SOLUTION.md) | 更完整的调研、方案 A/B/C/D、HITL 适配评估 |
| [hid2msp.py](hid2msp.py) | HID → MSP 接收机桥 |
| [hid2msp_xiaoweng.json](hid2msp_xiaoweng.json) | **当前实际使用**的手柄/遥控器映射 |
| [hid2msp.example.json](hid2msp.example.json) | 通用 Xbox 风格示例 |
| [calibrate_hid.py](calibrate_hid.py) | 交互式摇杆标定脚本 |
| [XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt](XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt) | **唯一 SITL CLI 源配置** |
| [start_sitl.sh](start_sitl.sh) | 启动 SITL |
| [start_bridge.sh](start_bridge.sh) | 启动手柄桥 |
| [check_ports.sh](check_ports.sh) | 检查 5760–5763 |
| `docs/architecture.png` | 架构图 |
| `docs/startup.png` | 启动时序图 |
| `docs/sequence.png` | 运行时序图 |
| `docs/make_diagrams.py` | 重新生成三张图 |
| `.sitl/plane.bin` | SITL 运行时 eeprom（配置真正生效的地方） |

> `.sitl/` 是运行时目录，不是源码。不要直接编辑 `plane.bin`，用 Configurator/CLI 修改。

---

## 3. 安装

### 3.1 X-Plane 11

1. 安装/确认 **X-Plane 11.55r2**（Steam 或独立版均可）。
2. 找到 X-Plane 根目录。Steam 版通常是：

```text
~/Library/Application Support/Steam/steamapps/common/X-Plane 11
```

3. 复制 INAV Surfwing 飞机和插件：

```bash
XP="$HOME/Library/Application Support/Steam/steamapps/common/X-Plane 11"
cp -R "INAV-X-Plane-HITL/release/Aircraft/Extra Aircraft/NK_FPVSurfwing" \
      "$XP/Aircraft/Extra Aircraft/"
```

4. 去掉 quarantine：

```bash
xattr -rd com.apple.quarantine \
  "$XP/Aircraft/Extra Aircraft/NK_FPVSurfwing"
```

5. 启动 X-Plane，进入：

```text
New Flight → Select Aircraft → Show extra aircraft from old versions
→ Extra Aircraft → INAV Surfwing
```

> `Show extra aircraft from old versions` 在 **Select Aircraft 窗口底部**，不在 `Settings → General`。

### 3.2 INAV Configurator 9.0.0

安装 macOS 版 INAV Configurator 9.0.0。它自带 SITL：

```text
/Applications/INAV Configurator 9.0.0.app/Contents/Resources/sitl/macos/inav_SITL
```

确认：

```bash
"/Applications/INAV Configurator 9.0.0.app/Contents/Resources/sitl/macos/inav_SITL" --help
```

应显示 `INAV 9.0.0 SITL`。

> 不要修改 `/Applications/INAV Configurator 9.0.0.app` 内的文件；本项目只调用它自带的 SITL。

### 3.3 Python 和 pygame

```bash
python3 -m pip install --upgrade pygame
python3 hid2msp.py --list
```

`--list` 会打印手柄名称、轴数/按键数，并实时显示：

```text
axes=[...] buttons=[...]
```

如果 macOS 拦截输入，给 Terminal/iTerm 打开：

```text
系统设置 → 隐私与安全性 → 输入监控
```

### 3.4 HID 设备

当前验证设备：

```text
PengFei Model RC Simulator - XTR+G2+FMS Controller
6 axes, 4 buttons
```

设备可以是一个 USB 模拟器适配器，也可以是把遥控器当 USB HID 的设备。只要 `--list` 能看到，就能用。

---

## 4. 通道定义

### 4.1 当前 `hid2msp_xiaoweng.json`

| 通道 | 功能 | 来源 |
|---|---|---|
| CH1 | Roll | `axis 5` |
| CH2 | Pitch | `axis 0` |
| CH3 | Throttle | `axis 1` |
| CH4 | Yaw | `axis 4` |
| CH5 | 旋钮三档原始指示 | `axis 3`，`tri` |
| CH6 | SWC → NAV WP | `button 3`，高=开 |
| CH7 | SWB → ARM | `button 2`，高=解锁 |
| CH8 | 六段模式 | `axis 3`，`multi` 6 档 |
| CH9 | NAV LAUNCH | 常高 `2000` |

### 4.2 六段模式

| 旋钮位置 | CH8 | 模式 |
|---|---|---|
| 最低 | 1000 | ANGLE |
| 低 | 1200 | HORIZON |
| 中低 | 1400 | MANUAL |
| 中高 | 1600 | NAV CRUISE |
| 高 | 1800 | NAV POSHOLD |
| 最高 | 2000 | NAV RTH |

- **SWC 高**：额外打开 **NAV WP**（`aux 8 28 1 1950 2050`）。
- **SWB 高**：ARM（`aux 0 0 2 1950 2050`）。
- **CH9 常高**：NAV LAUNCH 永久启用（`aux 7 36 4 1950 2050`）。

> 安全提醒：NAV LAUNCH 永久启用意味着解锁后飞控会进入起飞模式。SITL 里没有物理危险，但真机配置绝对不要照搬；每次解锁前确认桨叶周围无人。

---

## 5. 配置文件定义

### 5.1 `hid2msp_xiaoweng.json`

```json
{
  "host": "127.0.0.1",
  "port": 5762,
  "rate_hz": 50,
  "axes": [
    {"axis": 5, "channel": 1, "kind": "bipolar", "trim": 1500, "reverse": false},
    {"axis": 0, "channel": 2, "kind": "bipolar", "trim": 1500, "reverse": false},
    {"axis": 1, "channel": 3, "kind": "bipolar", "trim": 1500},
    {"axis": 4, "channel": 4, "kind": "bipolar", "trim": 1500},
    {"axis": 3, "channel": 8, "kind": "multi", "levels": 6,
     "values": [1000, 1200, 1400, 1600, 1800, 2000]},
    {"axis": 3, "channel": 5, "kind": "tri", "threshold": 0.0}
  ],
  "buttons": [
    {"button": 3, "channel": 6, "low": 1000, "high": 2000, "toggle": false},
    {"button": 2, "channel": 7, "low": 1000, "high": 2000, "toggle": false}
  ],
  "constants": {"9": 2000}
}
```

字段：

| 字段 | 说明 |
|---|---|
| `host` / `port` | SITL 的 RC UART（默认 `127.0.0.1:5762`） |
| `rate_hz` | RC 帧率，默认 50 Hz |
| `axes[].axis` | pygame/SDL 的轴编号，用 `--list` 确认 |
| `axes[].channel` | 目标 RC 通道（1–16） |
| `axes[].kind` | `bipolar`、`unipolar`、`tri`、`binary`、`multi` |
| `axes[].reverse` | 反向 |
| `axes[].trim` | 中位/低端 PWM |
| `axes[].deadband` / `expo` | 死区/曲线 |
| `axes[].threshold` | `tri`/`binary` 的切换阈值 |
| `axes[].levels` / `values` | `multi` 的档位数和每档 PWM |
| `buttons[].button` | 按键编号 |
| `buttons[].channel` | 目标通道 |
| `buttons[].low` / `high` | 松开/按下（或开关低/高）的 PWM |
| `buttons[].toggle` | `true` 为按一下切换，`false` 为跟随开关状态 |
| `constants` | 固定通道值；CH9=2000 就是 NAV LAUNCH |

`channel_map` 和 `mode_table` 只是文档字段，程序会忽略，方便人读。

> 同一个 `axis3` 同时给 CH8 做 6 档模式、给 CH5 做三档原始指示；CH5 不参与模式选择，可以删掉。


### 5.2 `XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt`

这是 INAV CLI 配置，核心内容：

```text
# UART 映射（serial 的 id 从 0 开始）
# serial 0 = UART1 = 5760 Configurator
# serial 1 = UART2 = 5761 HITL 插件
# serial 2 = UART3 = 5762 手柄桥
# serial 3 = UART4 = 5763 MSP DisplayPort
serial 0 1 115200 115200 0 115200
serial 1 1 115200 115200 0 115200
serial 2 1 115200 115200 0 115200
serial 3 33554432 115200 115200 0 115200

set receiver_type = MSP
set gps_provider = FAKE
set acc_hardware = FAKE
set baro_hardware = FAKE
set mag_hardware = FAKE
set pitot_hardware = FAKE
set rangefinder_hardware = NONE
set opflow_hardware = NONE
set rssi_source = NONE
set osd_video_system = AVATAR

# aux 的第 3 个参数是 0 基通道号：
# 2 = CH7, 3 = CH8, 4 = CH9, 1 = CH6
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

`aux` 的模式编号是 INAV 的 **permanent ID**：

| permanent ID | 模式 |
|---|---|
| 0 | ARM |
| 1 | ANGLE |
| 2 | HORIZON |
| 12 | MANUAL |
| 53 | NAV CRUISE |
| 11 | NAV POSHOLD |
| 10 | NAV RTH |
| 36 | NAV LAUNCH |
| 28 | NAV WP |

### 5.3 SITL 每次启动到底读哪个文件

**SITL 启动时只读 `.sitl/plane.bin`。**

```bash
./start_sitl.sh
# 等价于：
# inav_SITL --path="$PWD/.sitl/plane.bin"
```

启动顺序和数据流：

```text
XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt   （人可读的 CLI 源文件）
        │  只在 Configurator CLI 里手动粘贴/加载
        ▼
.sitl/plane.bin                        （32 KB 飞控 eeprom）
        │  每次 SITL 启动 --path 读取
        ▼
INAV SITL 运行时配置
```

因此：

- 修改 `XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt` **不会**自动影响正在运行的 SITL；必须重新在 CLI 里加载并 `save`，或重新生成 `.sitl/plane.bin`。
- `start_sitl.sh` 不会读 `.txt`；它只把 `.sitl/plane.bin` 传给 `--path`。
- 如果 `.sitl/plane.bin` 不存在，SITL 会生成一份**默认配置**，不是本项目配置；需要按 7.7 加载 CLI。
- 不要直接编辑 `.sitl/plane.bin`（二进制）；用 Configurator/CLI 修改后 `save`。
- 不要在 INAV 9 SITL 上反复执行 `defaults noreboot` + 连续灌 CLI；本次实际遇到过崩溃。需要重置时优先删除/备份 `.sitl/plane.bin`，让 SITL 生成全新 eeprom，再加载 NODEFAULTS 版本。

---

## 6. 启动顺序

推荐开三个终端 + X-Plane。

### 6.1 终端 A：SITL

> 首次使用或 `.sitl/plane.bin` 丢失时：SITL 会生成默认配置（不是本项目配置）。先启动 SITL，用 Configurator 连接 5760，按 [7.7](#77-加载-cli-配置) 加载 `XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt`，`save` 并重启 SITL，再继续。

```bash
cd "$HOME/Desktop/Read-the-Source-Code/hid-as-rx"
./start_sitl.sh
```

或手动：

```bash
SITL="/Applications/INAV Configurator 9.0.0.app/Contents/Resources/sitl/macos/inav_SITL"
"$SITL" --path="$PWD/.sitl/plane.bin"
```

启动后应有：

```text
[EEPROM] Loaded ... .sitl/plane.bin
[SOCKET] Bind TCP [::]:5760 to UART1
[SOCKET] Bind TCP [::]:5761 to UART2
[SOCKET] Bind TCP [::]:5762 to UART3
[SOCKET] Bind TCP [::]:5763 to UART4
```

### 6.2 终端 B：手柄桥

先把 **SWB 拨到低位（锁定）**，再：

```bash
cd "$HOME/Desktop/Read-the-Source-Code/hid-as-rx"
./start_bridge.sh
```

或：

```bash
python3 hid2msp.py --config hid2msp_xiaoweng.json --port 5762 -v
```

### 6.3 检查端口

```bash
./check_ports.sh
```

期望：

```text
5760 open
5761 open
5762 open
5763 open
```

### 6.4 X-Plane

1. 启动 X-Plane 11；
2. 加载 **INAV Surfwing**；
3. 进入：
   ```text
   Plugins → INAV HITL/SITL → Connect to SITL → 127.0.0.1:5761
   ```
4. 菜单变成 `Disconnect from SITL` 即连接成功。

### 6.5 Configurator（需要改配置时）

1. 打开 INAV Configurator 9.0.0；
2. 连接方式选 **TCP**；
3. 地址：
   ```text
   127.0.0.1:5760
   ```

### 6.6 停止

```bash
pkill -f hid2msp.py
pkill -f inav_SITL
```

X-Plane 里先 `Plugins → INAV HITL/SITL → Disconnect from SITL`，再退出。

---

## 7. 用 INAV Configurator 配置 SITL

### 7.1 Receiver

- Receiver type：**MSP**
- 不要选 `SIM (SITL)`（那是 X-Plane 原生摇杆模式，不走 `hid2msp.py`）
- 不要选 `SERIAL`（除非你接真实串口接收机）

### 7.2 Ports

| UART | 功能 | 对应端口 |
|---|---|---|
| UART1 | MSP | 5760 |
| UART2 | MSP | 5761 |
| UART3 | MSP | 5762 |
| UART4 | MSP DisplayPort | 5763 |

注意：CLI 的 `serial` id 从 **0** 开始，所以：

```text
serial 0 = UART1
serial 1 = UART2
serial 2 = UART3
serial 3 = UART4
```

### 7.3 Mixer

- Platform：**AIRPLANE**
- 当前配置保留真实 XiaoWeng 的 mixer（`model_preview_type = 26`，双发固定翼）。
- HITL 插件只使用 roll/pitch/yaw/throttle 四个控制量，不读取每个舵机输出；所以 INAV 的 mixer 不会逐个映射到 X-Plane 舵面。
- 不要在 SITL 里选 `Flying Wing` 再期待 X-Plane 看到左右 elevon；标准桥只传 4 个控制轴。

### 7.4 Sensors

| 项目 | 设置 |
|---|---|
| Accelerometer | `FAKE` |
| Barometer | `FAKE` |
| Magnetometer | `FAKE` |
| Pitot | `FAKE` |
| Rangefinder | `NONE` |
| Optical flow | `NONE` |
| GPS | `FAKE` |

`ins_gravity_cmss`、`acczero/accgain`、`magzero/maggain`、`gyro_zero` 这些是真机校准值，SITL 不需要，已从精简配置里移除。

### 7.5 OSD

- Configuration → Other features：勾选 `OSD`
- OSD → Video system：`AVATAR`（也支持 `HDZERO`、`DJIWTF`、`BF43COMPAT`）
- Ports → UART4：`MSP DisplayPort`

SITL 没有模拟 MAX7456 模拟 OSD；必须走 **MSP DisplayPort + HD OSD**，否则 HITL 插件会提示 `SUPPORTED OSD TYPE NOT FOUND`。UART4 本身不直接给 X-Plane 送画面，它只是 SITL 内部的 OSD 显示端口；插件通过 5761 的 MSP_SIMULATOR 读取 OSD 内容并绘制。

### 7.6 Modes

| 通道 | 作用 |
|---|---|
| CH6 | SWC → NAV WP（高=开） |
| CH7 | SWB → ARM（高=解锁） |
| CH8 | 旋钮六段模式 |
| CH9 | 常高 → NAV LAUNCH |

如果 AUX 表丢了，用 `XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt` 重新加载。

### 7.7 加载 CLI 配置

1. Configurator 连接 `127.0.0.1:5760`；
2. 进入 CLI；
3. 粘贴 [XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt](XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt) 的内容；
4. `save`；
5. SITL 重启后重新连接。

> 如果从“非全新 eeprom”恢复，先备份 `.sitl/plane.bin`，再按需使用带 `defaults noreboot` 的版本；遇到 SITL 崩溃就改用 NODEFAULTS 版本 + 全新 eeprom。

---

## 8. 操作流程

### 8.1 解锁

1. 油门最低；
2. 左右摇杆回中；
3. SWB 拨到高位；
4. Configurator 的 Receiver 页确认 **CH7 = 2000**；
5. 解锁。

如果 SWB 高位时 CH7 还是 1000，把 JSON 里的 `low/high` 对调。

### 8.2 模式选择

- 旋钮：CH8 六档模式；
- SWC 高：叠加 NAV WP；
- CH9 常高：NAV LAUNCH 永久启用。

### 8.3 失控保护

- INAV `failsafe_procedure = RTH`；
- `hid2msp.py` 停止/崩溃后，SITL 超过约 200 ms 收不到 RC 帧，进入 failsafe；
- 测试方法：地面解锁前，先停掉手柄桥，看 Configurator/OSD 是否进入 FS。

---

## 9. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 没有 `INAV HITL/SITL` 菜单 | 没加载 INAV Surfwing；插件是 Aircraft 插件 | 加载 `INAV Surfwing`；Select Aircraft 里勾选 `Show extra aircraft from old versions` |
| `UNSUPPORTED AIRCRAFT TYPE` | SITL 平台不是 AIRPLANE | Configurator → Mixer → Platform `AIRPLANE`；或加载已包含 `set platform_type = AIRPLANE` 的配置 |
| `SUPPORTED OSD TYPE NOT FOUND` | 没有 MSP DisplayPort/HD OSD | UART4 设为 `MSP DisplayPort`，OSD video `AVATAR`，OSD feature 打开 |
| `unable to arm no rc link` / `FS` | 手柄桥没运行，5762 没有 MSP 帧 | 启动 `hid2msp.py`；`./check_ports.sh` 确认 5762 |
| 只有 3 个模式 | 旧版用 SWC 做 2×3，SWC 没真正改变 CH6 | 当前版本已改成旋钮直接 6 档；确认 CH8 是否 1000/1200/…/2000 |
| Pitch 反向 | `reverse` 方向不对 | 改 `hid2msp_xiaoweng.json` 里 CH2 的 `reverse`，重启桥 |
| 启动桥就自动解锁 | SWB 在高位 | 先拨 SWB 低位，确认 CH7=1000 |
| `INS_GRAVITY_CMSS` 大字体 | 真机 IMU 校准 system message | 用精简配置，删除 `ins_gravity_cmss`；SITL 值为 0 |
| SITL CLI 加载崩溃 | `defaults noreboot` + 连续灌命令 | 删除/备份 `.sitl/plane.bin`，用全新 eeprom + `XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt` |
| Gatekeeper 拦截插件 | quarantine | `xattr -rd com.apple.quarantine .../NK_FPVSurfwing` |
| Apple Silicon 上 X-Plane 11 打不开 | X-Plane 11 是 x86_64 | 安装 Rosetta 2；`softwareupdate --install-rosetta --agree-to-license` |
| 端口被占用 | 旧 SITL/桥没退 | `pkill -f inav_SITL`、`pkill -f hid2msp.py`，再 `./check_ports.sh` |

---

## 10. 当前状态与限制

### 10.1 当前状态

- X-Plane 11.55r2 已安装 INAV Surfwing + HITL 插件；
- INAV SITL 9.0.0 运行在 `.sitl/plane.bin`；
- 四个 TCP 端口 5760–5763；
- `hid2msp.py` 已按实际 HID 标定：
  - Roll=axis5、Pitch=axis0、Throttle=axis1、Yaw=axis4、Knob=axis3；
  - SWC=button3、SWB=button2；
- OSD 走 UART4 MSP DisplayPort + AVATAR；
- SWC 已配置为 NAV WP；
- `ins_gravity_cmss` 已从 SITL 配置移除。

### 10.2 限制

- HITL 插件只支持 **Airplane**，且只回传 roll/pitch/yaw/throttle；INAV 的每个舵机混控不会逐个出现在 X-Plane。
- SITL 没有模拟 MAX7456；OSD 必须走 MSP DisplayPort。
- 当前 HID 适配器把原 SWA 只编码成 `button0` 的 0/1，无法得到三档；所以改用 **axis3 旋钮** 做 6 档模式。
- HITL 插件 v1.5.0 主要面向 INAV 7/8；INAV 9.0 联调时如遇协议差异，需要降级或改插件。
- X-Plane 11 在 Apple Silicon 上通过 Rosetta 运行；X-Plane 12 原生 arm64 需要 arm64/universal 插件。
- 本配置仅用于 SITL，**不要刷入真实飞机**。

---

## 11. 安全

- 这是仿真环境，但 **NAV LAUNCH 永久启用**；解锁前确认模型/桨叶周围无人。
- 真机配置文件是只读参考，不要直接把 `XIAOWENG_SITL_MINIMAL_NODEFAULTS.txt` 刷入真机。
- 真机使用前重新检查：传感器校准、 failsafe、arm 开关方向、模式优先级、电机/舵机方向。
- 修改 `hid2msp_xiaoweng.json` 后重启桥，确认 Configurator 的 CH1–CH9 再解锁。

---

## 12. 参考

- INAV SITL 文档：<https://github.com/iNavFlight/inav/blob/master/docs/SITL/SITL.md>
- INAV X-Plane 文档：<https://github.com/iNavFlight/inav/blob/master/docs/SITL/X-Plane.md>
- INAV-X-Plane-HITL：<https://github.com/RomanLut/INAV-X-Plane-HITL>
- ArduPilot X-Plane SITL（替代方案）：<https://ardupilot.org/dev/docs/sitl-with-xplane.html>
- pygame：<https://www.pygame.org/>

更完整的方案对比（A/B/C/D、HITL 插件 macOS 适配评估）见 [SOLUTION.md](SOLUTION.md)。
