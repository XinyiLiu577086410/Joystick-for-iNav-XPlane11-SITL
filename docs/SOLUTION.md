# macOS 上 X-Plane 11 + INAV SITL + HID 手柄当 Receiver：调研与实施方案

> 本文件是 **macOS 分支（main）** 的调研与设计记录，在 `windows` 分支上仅作参考；
> Windows 的实现与操作说明见 [README.md](../README.md)。

> 当前实际使用的安装、启动、通道映射和 Configurator 配置见 [docs/README-macos.md](README-macos.md)；本文是方案调研与历史设计记录。

> 适用环境：macOS（Intel / Apple Silicon）、X-Plane 11.55、INAV Configurator 9.x、INAV SITL 9.0.0  
> 结论先行：**可行**。先走方案 A（零代码，30–60 分钟能飞）；需要“手柄像 MSP 接收机、16 通道、按键做模式”时走方案 B；只有必须验证 INAV 自身 elevon/V-tail 混控时，才需要方案 C 的自定义舵面桥。

## 0. 最快路径（TL;DR）

1. X-Plane 11 启动，进跑道；`Settings → Network` 勾选 “Accept incoming connections”，接收端口设为 **49001**。
2. 手柄在 X-Plane `Settings → Joystick` 校准；Roll/Pitch/Yaw 对应 CH1/CH2/CH4，**Cowl Flap 1** 对应 CH3（油门），Cowl Flap 2–5 对应 CH5–CH8。
3. Configurator → SITL，选 `[Standard] X-Plane`，端口 49001，channel map 用 `M01-01,S03-02,S01-03,S04-04`，启动 SITL。
4. Configurator 连上 SITL；Receiver type 选 `SIM (SITL)`；Mixer 选 `Airplane`（有尾翼，不要选 Flying Wing）；传感器选 FAKE。
5. 动杆看 Receiver 页，解锁（CH5）推油。能飞就到此为止；要按键/16 通道/INAV 混控再往下看方案 B/C。

---

## 1. 结论与选型

| 目标 | 推荐方案 | 代码量 | 手柄输入 | 混控在哪 | X-Plane 里能看到 INAV 混控吗 |
|---|---|---|---|---|---|
| 只想用手柄在 X-Plane 里飞，INAV 在环 | **A. 原生 SITL + X-Plane 摇杆** | 0 | X-Plane 读 HID，8 轴 | X-Plane 机型 | 不能（看到的是 X-Plane 的混控） |
| 手柄像接收机：16 通道、按键、可接 HITL 插件 | **B. HID → MSP_SET_RAW_RC** | 一个 Python 桥 | 自写桥，16 通道 | INAV（可 bench 验证） | 不能（HITL 只回传 4 个轴） |
| 必须验证 INAV 的 elevon / V-tail 混控 | **C. MSP_SERVO → X-Plane 舵面 DREF** | 自定义桥/插件 | B 的桥 | INAV | 能 |
| 不想写桥，且要 FC 侧混控 + 摇杆 | **D. ArduPilot SITL** | 0（官方支持） | X-Plane 读 HID，JSON 映射 | ArduPilot | 能（按 JSON 映射舵面） |

### 1.1 三个关键事实

1. **macOS 版 INAV Configurator 自带 SITL 可执行文件**，而且是 universal binary（x86_64 + arm64），不需要自己编译。本机文件：
   `3rdparty/inav-configurator/resources/public/sitl/macos/inav_SITL`
   运行 `--help` 显示 `INAV 9.0.0 SITL`。

2. **INAV SITL 原生支持 X-Plane 11/12**，通过 X-Plane 的 UDP `RREF`/`DREF` 接口，不是必须装 HITL 插件。`--sim=xp` 就是原生模式。

3. **原生 X-Plane 接口只传“控制轴”，不传“每个舵机”**：它从 X-Plane 读 8 个摇杆轴当 RC 通道，向 X-Plane 写 1 个油门 + 3 个控制轴（roll/pitch/yaw）。HITL 插件也只回传 roll/pitch/yaw/throttle。因此：
   - **INAV 的混控可以在 INAV 内部算，但标准 X-Plane 桥不会把每个舵机的输出分别画到 X-Plane 的舵面上。**
   - 想让 X-Plane 里的飞机正确飞行，最简单的做法是：**INAV 按“常规固定翼（有尾翼）”配置，让 X-Plane 的机型自己做 elevon/V-tail 混控。**
   - 想验证 INAV 自己的混控，只能在 Configurator 的 Servo 页看，或者做方案 C。

---

## 2. 调研：INAV SITL 的输入/输出链路

### 2.1 SITL 的 RC 输入方式

INAV SITL 支持以下 Receiver 类型（Configurator 的 Receiver 页选择）：

| 类型 | 说明 | 通道数 | 适合 |
|---|---|---|---|
| `SIM (SITL)` | 从模拟器读摇杆轴；X-Plane 原生模式 | 8 | 方案 A |
| `MSP` | 通过 MSP `SET_RAW_RC` 注入 | 16+ | 方案 B / HITL |
| `SERIAL` | 通过 `--serialport` 把真实串口接收机映射进 SITL | 取决于协议 | 真接收机 |
| `NONE` | 无接收机 | 0 | 仅 Configurator |

`SIM` 的实现见 `src/main/rx/sim.c`：`rxSimSetChannelValue()` 写入通道，`rxSimFrameStatus()` 按帧返回。X-Plane 原生接口在 `src/main/target/SITL/sim/xplane.c` 中调用它。

`MSP` 的实现见 `src/main/rx/msp.c`；MSP 命令 `MSP_SET_RAW_RC`（200）在 `src/main/fc/fc_msp.c` 中处理，payload 是 N 个 little-endian `uint16`，单位 µs。SITL 的 UART 被映射为 TCP：

- UART1 → 5760
- UART2 → 5761
- UART3 → 5762
- ……以此类推（`--tcpbaseport` 可改基址）

每个 UART 同时只能有一个 TCP 客户端，所以 Configurator、HITL 插件、手柄桥要各占一个 UART。

> **本机已验证**：在 macOS arm64 上运行 `inav_SITL`（INAV 9.0.0），通过 TCP 向 UART1 发送 `MSP_SET_RAW_RC` 帧，再读取 `MSP_RC`，确认 CH1–CH8 会随发送值变化。也就是说，方案 B 的“TCP + MSP 原始通道”链路是通的；剩下的只是把手柄读数接到这个帧上。

### 2.2 X-Plane 原生接口到底读/写什么

`xplane.c` 中注册的 X-Plane datarefs：

**读入（X-Plane → SITL，作为 RC）：**

| X-Plane dataref | 代码里的通道 | 用途 |
|---|---|---|
| `sim/joystick/joy_mapped_axis_value[2]` | CH1 | Roll |
| `sim/joystick/joy_mapped_axis_value[1]` | CH2 | Pitch |
| `sim/joystick/joy_mapped_axis_value[57]` | CH3 | Throttle（借用了 Cowl Flap 1） |
| `sim/joystick/joy_mapped_axis_value[3]` | CH4 | Yaw |
| `sim/joystick/joy_mapped_axis_value[58..61]` | CH5–CH8 | 借用 Cowl Flap 2–5 |

前提是 `sim/joystick/has_joystick >= 1`，也就是 X-Plane 里至少识别到一个摇杆/手柄。

**写出（SITL → X-Plane，作为舵面/油门）：**

| INAV 输出 | X-Plane dataref |
|---|---|
| 电机（Motor） | `sim/cockpit2/engine/actuators/throttle_ratio_all` |
| 第 1 个非电机输出 | `sim/joystick/yoke_roll_ratio` |
| 第 2 个非电机输出 | `sim/joystick/yoke_pitch_ratio` |
| 第 3 个非电机输出 | `sim/joystick/yoke_heading_ratio` |

同时会设置 `sim/operation/override/override_joystick = 1`，接管 X-Plane 的摇杆输入。

**关键限制：只有 3 个非电机输出会被使用。** 所以 `--chanmap` 不是“把 S1/S2/S3/S4 原样送进 X-Plane 的四个舵面”，而是“挑 3 个 INAV 输出当作 roll/pitch/yaw 三个控制轴”。

### 2.3 标准 X-Plane 配置文件的 channel map

Configurator 的 SITL 页对 X-Plane 使用 4 个输出槽：

```
槽 1 = Throttle
槽 2 = Roll
槽 3 = Pitch
槽 4 = Yaw
```

标准 “Airplane” 混控预设（Configurator 的 Mixer 页）是：

- S1 = Elevator（pitch）
- S2 = Flapperon 1（roll）
- S3 = Flapperon 2（roll）
- S4 = Rudder（yaw）
- M1 = Motor

因此标准 channel map 是：

```text
M01-01,S03-02,S01-03,S04-04
```

含义：

- 电机 M1 → 槽 1（油门）
- S3（Flapperon 2，作为 roll 代表）→ 槽 2（Roll）
- S1（Elevator）→ 槽 3（Pitch）
- S4（Rudder）→ 槽 4（Yaw）
- S2（Flapperon 1）不参与，因为 X-Plane 只需要一个 roll 轴，它会自己把 roll 分配给左右副翼。

这也是 `3rdparty/inav/docs/SITL/X-Plane.md` 里给出的示例。注意：这个 map 只对“Airplane（有尾翼）”预设成立；如果你在 INAV 里选 Flying Wing，S1/S2 是左右 elevon，再这样映射就会把混控“混两次”，飞机动作会不对。

### 2.4 HITL 插件的能力边界

`INAV-X-Plane-HITL` 是给 **真实飞控** 做 HITL 的 X-Plane 插件，也支持连接 INAV SITL（v1.4.0+）。它负责：

- 把 X-Plane 的 IMU/GPS/气压/磁罗盘/空速/电池等传感器数据通过 MSP 发给 FC；
- 把 FC 回传的 roll/pitch/yaw/throttle 写进 X-Plane；
- 在 X-Plane 里画 OSD；
- 提供一些故障注入、续航模拟等。

它**不传每个舵机的输出**。`TMSPSimulatorFromINAV` 里只有 4 个控制量：

```c
int16_t roll;
int16_t pitch;
int16_t yaw;
int16_t throttle;
```

所以：

- 用 HITL 插件时，INAV 的 elevon/V-tail 混控不会体现在 X-Plane 的左右舵面上；
- 插件文档也明确说“不需要配置混控和电机输出”“Platforms other than Airplane are not supported”；
- 插件模式下，SITL 的摇杆输入不可用（官方 SITL 文档写明 “Not available with INAV-X-Plane-HITL plugin”），所以手柄必须走 MSP 桥或串口接收机。

### 2.5 混控到底发生在哪一层

| 配置 | INAV 混控 | X-Plane 混控 | 结果 |
|---|---|---|---|
| INAV `Airplane` + X-Plane 飞翼/V-tail 机型 | 只输出 aileron/elevator/rudder 三个逻辑轴 | X-Plane 机型把 roll/pitch 混成 elevon，或把 pitch/yaw 混成 V-tail | ✅ 推荐，动作正确 |
| INAV `Flying Wing` + 标准 X-Plane 桥 | INAV 输出左右 elevon | X-Plane 又把 roll/pitch 混一次 | ❌ 双重混控，动作错误 |
| INAV `Flying Wing` + Configurator Servo 页 | INAV 输出左右 elevon | 不涉及 X-Plane | ✅ 只能地面验证混控 |
| INAV `Flying Wing` + 方案 C 自定义舵面桥 | INAV 输出左右 elevon | 直接写左右 elevon 舵面 | ✅ 完整验证 |

**一句话：标准工具链里，X-Plane 看到的是“三个控制轴”，不是“四个舵机”。混控要么交给 X-Plane 的机型，要么自己写舵面桥。**

---

## 3. 方案 A：原生 SITL + X-Plane 摇杆（推荐先做）

### 3.1 架构

```text
HID 手柄
   │  macOS HID / SDL2 / X-Plane 原生驱动
   ▼
X-Plane 11  ──UDP RREF/DREF (49000/49001)──►  INAV SITL (--sim=xp)
   ▲                                              │
   └────────── yoke roll/pitch/yaw + throttle ◄───┘
```

没有额外进程，没有 Python 桥。X-Plane 既当“遥控器”，又当“被控对象”。

### 3.2 准备

1. **X-Plane 11**
   - Apple Silicon 上 X-Plane 11 是 Intel 程序，需要 Rosetta 2。第一次启动若提示，安装：
     ```bash
     softwareupdate --install-rosetta --agree-to-license
     ```
   - **先确认 X-Plane 11 能在你的 macOS 上正常启动和加载飞机**。如果 macOS 版本太新导致 X-Plane 11 崩溃，改用 X-Plane 12；INAV SITL 同样支持，HITL 插件也声明支持 11/12。
   - 没有正版可用 15 分钟 Demo：<https://www.x-plane.com/desktop/try-it/older/>
   - 设置 `Settings → General → Flight models per frame = 10`（小飞机更稳）。

2. **INAV Configurator**
   - 安装 macOS 版；如果 Gatekeeper 拦截：
     ```bash
     xattr -dr com.apple.quarantine "/Applications/INAV Configurator.app"
     ```
   - 确认 SITL 二进制可执行：
     ```bash
     chmod +x "/Applications/INAV Configurator.app/Contents/Resources/app.asar.unpacked/resources/public/sitl/macos/inav_SITL"
     ```
     路径因打包方式可能不同，也可以直接用本仓库的：
     ```bash
     chmod +x 3rdparty/inav-configurator/resources/public/sitl/macos/inav_SITL
     ```

3. **手柄**
   - Xbox One/Series、PS4/PS5、8BitDo、Radiomaster/Jumper 的 USB 摇杆模式都可以。
   - 先在 macOS“系统设置 → 游戏控制器”里确认能看到；必要时给 Terminal/iTerm 开“输入监控”权限。
   - 不建议用需要内核驱动的老 Xbox 360 有线手柄（Apple Silicon 上更麻烦）。

### 3.3 X-Plane 网络设置

`Settings → Network`：

- 勾选 **Accept incoming connections**。
- **Port we receive on**：设成和 SITL 的 `--simport` 一致。Configurator SITL 页默认是 **49001**；命令行默认是 **49000**。
- **Port we send from**：保持 49000（不要和 receive 端口相同）。
- macOS 防火墙弹窗时允许 X-Plane 接收连接。

> 如果 SITL 一直显示 `Waiting for connection...`，先把 receive 端口在 49000/49001 之间换一下，确认两边一致。

### 3.4 X-Plane 手柄设置

`Settings → Joystick`：

1. 选中手柄，校准所有轴。
2. 按下面的表分配轴功能（X-Plane 的轴功能名在下拉列表里）：

| X-Plane 轴功能 | INAV 通道 | 建议物理轴 |
|---|---|---|
| Roll | CH1 | 左摇杆左右 |
| Pitch | CH2 | 左摇杆前后（必要时 Reverse） |
| Yaw | CH4 | 右摇杆左右 |
| Cowl Flap 1 | CH3（油门） | 右摇杆前后，或扳机 |
| Cowl Flap 2 | CH5（ARM） | 扳机/旋钮/滑块 |
| Cowl Flap 3 | CH6（ANGLE/HORIZON） | 扳机/旋钮/滑块 |
| Cowl Flap 4 | CH7 | 备用 |
| Cowl Flap 5 | CH8 | 备用 |

注意：

- 不要用 X-Plane 的 “Throttle” 轴功能给 INAV 油门；代码读的是 `joy_mapped_axis_value[57]`，对应 **Cowl Flap 1**。
- X-Plane 的轴值方向可能和 INAV 相反，先在 Configurator 的 Receiver 页看通道条，再回 X-Plane 勾 Reverse。
- 手柄只有 4 个模拟轴时，CH5–CH8 只能用扳机/滑块；想要按键做模式，直接上方案 B。

### 3.5 INAV SITL 配置

**最简单：用 Configurator 的 SITL 页。**

1. 打开 Configurator → SITL。
2. 选择内置的 **`[Standard] X-Plane`** 配置（或新建一个）。
3. Simulator 选 **X-Plane**，IP `127.0.0.1`，Port `49001`。
4. 确认 channel map 是：
   ```text
   M01-01,S03-02,S01-03,S04-04
   ```
   也就是 UI 里的 `Throttle / Roll / Pitch / Yaw` 四行。
5. **不要勾** “Serial receiver”（除非你真的接串口接收机）。
6. 点 Start SITL。
7. Configurator 用 SITL/TCP 连上（5760 或 5761）。

**然后检查/设置：**

- Receiver 页：Receiver type = **SIM (SITL)**。
- Mixer 页：平台 `Airplane`，预设 `Airplane`（有尾翼），不要选 `Flying Wing`。
  - 如果你要自己定义 3 舵机，也可以在 Custom Airplane 里加：
    - S1 ← Stabilized Roll 100
    - S2 ← Stabilized Pitch 100
    - S3 ← Stabilized Yaw 100
  - 这时 channel map 要改成 `M01-01,S01-02,S02-03,S03-04`。
- Sensors：
  - Baro = FAKE
  - Mag = FAKE（或 QMC5883）
  - Pitot = FAKE / VIRTUAL
  - GPS = FAKE（X-Plane 原生接口会灌 GPS）
  - Battery = FAKE
- Modes：ARM 放 CH5，ANGLE/HORIZON 放 CH6；范围按默认 1700–2100 / 1300–1700 调。
- Failsafe：建议先设 `DROP` 或 `RTH`，并在 SITL 里测试。

**命令行等价写法：**

```bash
./3rdparty/inav-configurator/resources/public/sitl/macos/inav_SITL \
  --path="$HOME/Library/Application Support/inav-configurator/standard-x-plane.bin" \
  --sim=xp \
  --simip=127.0.0.1 \
  --simport=49001 \
  --chanmap=M01-01,S03-02,S01-03,S04-04
```

如果使用命令行，Configurator 就连 `127.0.0.1:5760`；不要同时让 SITL 页再启动一个实例（端口会冲突）。

### 3.6 启动顺序与验证

推荐顺序：

1. X-Plane 11 启动，选好机型，停在跑道上。
2. 启动 SITL。
3. Configurator 连接 SITL。
4. 在 Receiver 页动杆，确认 CH1–CH8 跟着动、方向正确、端点约 1000–2000。
5. 在 Servo 页确认 S1/S3/S4 的输出方向。
6. 解锁（CH5 打到高位），推油，观察 X-Plane 的舵面和飞机姿态。
7. 如果 roll/pitch 反了：先在 X-Plane 的 Joystick 设置里 Reverse，或在 INAV 的 Receiver 页调通道反向；不要在两边同时反。

### 3.7 优缺点

**优点：**

- 零代码，官方支持，最稳定。
- 不需要 HITL 插件，不需要 Python，不占额外 UART。
- 适合快速验证“手柄 → INAV → X-Plane”整条链路。

**缺点：**

- 只有 8 个轴，没有按键；模式开关要用扳机/滑块模拟。
- 手柄必须被 X-Plane 识别；X-Plane 的轴映射有点绕（Cowl Flap 1–5）。
- X-Plane 里看到的是 X-Plane 的混控，不是 INAV 的混控。
- 不能同时用 HITL 插件的 OSD/传感器注入（原生模式和插件模式二选一）。

---

## 4. 方案 B：HID → MSP Receiver（推荐给“手柄像接收机”）

### 4.1 架构

```text
HID 手柄
   │  pygame / SDL2
   ▼
scripts/hid2msp.py  ──TCP 5762, MSP_SET_RAW_RC──►  INAV SITL UART3 (receiver_type=MSP)
                                                   │
X-Plane 11 ◄── HITL 插件 ──TCP 5761, MSP──────────┘
                                                   │
Configurator ──TCP 5760, MSP───────────────────────┘
```

三个客户端各占一个 UART：

| 端口 | UART | 用途 |
|---|---|---|
| 5760 | UART1 | Configurator |
| 5761 | UART2 | INAV-X-Plane-HITL 插件 |
| 5762 | UART3 | `scripts/hid2msp.py` 手柄桥 |

### 4.2 为什么用 MSP，而不是虚拟串口/SBUS

- MSP 是 INAV 原生支持的 Receiver 类型，`receiver_type=MSP` 即可。
- 走 TCP，不需要 macOS 的 PTY、虚拟串口、SBUS 反相、波特率这些坑。
- 16 通道，按键可以映射成 ARM/模式开关。
- 实现简单：一个 TCP socket + 一个 6 字节 MSP 头 + 32 字节通道数据。

MSP v1 帧格式：

```text
$M<  len  cmd(200)  ch1_lo ch1_hi ... ch16_lo ch16_hi  xor
```

`len = 32`（16 通道 × 2 字节），`xor` 是 `len ^ cmd ^ payload...`。50 Hz 发送即可；INAV 的 `rxSignalTimeout` 是 200 ms，桥一停就会触发 failsafe。

### 4.3 SITL 配置

1. 启动 SITL（Configurator 的 SITL 页，**不要选 X-Plane/RealFlight**，即 configurator-only）。
2. 连接 Configurator（5760）。
3. Ports 页：把 **UART3** 设成 `MSP`，保存并重启 SITL。
   - 命令行等价（identifier 以 `serial` 输出为准；多数 INAV 版本 UART3 是 `2`）：
     ```text
     serial 2 1 115200 115200 115200 115200
     save
     ```
   - 重启后确认日志出现：
     ```text
     [SOCKET] Bind TCP [::]:5762 to UART3
     ```
4. Receiver 页：Receiver type = **MSP**。
5. Mixer 页：按你的机型选：
   - 想验证 INAV 混控：`Flying Wing` / `Airplane V-tail`。
   - 想在 X-Plane 里飞：`Airplane`（有尾翼），让 X-Plane 机型做混控。
6. Modes：ARM 放 CH5，ANGLE/HORIZON 放 CH6。
7. 保存。

### 4.4 手柄桥 `scripts/hid2msp.py`

本仓库已经提供：

- `scripts/hid2msp.py`：读取 HID 手柄，映射为 16 通道，通过 TCP 发 MSP。
- `config/hid2msp.example.json`：映射配置示例。

安装依赖：

```bash
python3 -m pip install --upgrade pygame
```

先看手柄的轴/按键编号：

```bash
python3 scripts/hid2msp.py --list
```

它会打印手柄名称、轴数、按键数，并实时显示 `axes=[...] buttons=[...]`。不同手柄的编号不同，必须按实际输出改配置。

默认映射（Xbox 风格）：

| 通道 | 功能 | 默认轴/按键 |
|---|---|---|
| CH1 | Roll | axis 0 |
| CH2 | Pitch | axis 1（反向） |
| CH3 | Throttle | axis 5（右扳机） |
| CH4 | Yaw | axis 2 |
| CH5 | ARM | button 0（A） |
| CH6 | ANGLE/HORIZON | button 1（B） |
| CH7 | 备用 | button 2 |
| CH8 | 备用 | button 3 |

改 `config/hid2msp.example.json` 后运行：

```bash
# 先空跑：不读手柄，发缓慢的正弦扫掠，CH5 保持 1000（不解锁）
python3 scripts/hid2msp.py --port 5762 --test -v

# 正式运行（需要手柄）
python3 scripts/hid2msp.py --config config/hid2msp.example.json --port 5762 -v
```

`--test` 适合在 Configurator 的 Receiver 页确认 MSP 链路和通道变化；它不读手柄。  
`--once` 只发一帧，适合脚本/CI 检查（可配合 `--test`）。

### 4.5 与 HITL 插件联用

1. 先启动 SITL（configurator-only）。
2. 启动 `scripts/hid2msp.py --port 5762`。
3. 启动 X-Plane，加载带 INAV-X-Plane-HITL 插件的机型（如 INAV Surfwing）。
4. 插件菜单 → `Connect to SITL` → 选 `127.0.0.1:5761`。
5. Configurator 仍连 5760。
6. 在 Configurator 的 Receiver 页确认手柄通道；在 Servo 页确认 INAV 混控；解锁试飞。

macOS 上插件未签名时：

```bash
xattr -rd com.apple.quarantine \
  "$HOME/Library/Application Support/Steam/steamapps/common/X-Plane 11/Aircraft/Extra Aircraft/NK_FPVSurfwing/plugins/INAV-X-Plane-HITL/64/mac.xpl"
```

路径按你的 X-Plane 安装位置调整。

> 版本提示：HITL 插件 v1.5.0 发布于 2024 年，主要针对 INAV 7/8 时代。INAV 9.0 SITL 的 MSP 协议若有变化，插件可能连不上或 OSD 不显示。遇到这种情况，优先用 INAV 8.x 的 SITL 二进制，或用插件仓库 main 分支重新编译；不要把“插件连不上”误判成手柄桥的问题。

### 4.6 混控怎么配

**如果你想在 Configurator 里看到 INAV 的 elevon/V-tail 混控：**

- Mixer 页选 `Flying Wing` 或 `Airplane V-tail`。
- Servo 页应能看到：
  - Flying Wing：S1 = roll + pitch，S2 = -roll + pitch；
  - V-tail：S3/S4 = pitch ± yaw。
- 用 `--test` 或手柄动杆，观察 Servo 输出条。  
  **这就是 INAV 混控的“地面验证”。**

**如果你想在 X-Plane 里飞：**

- INAV 仍选 `Airplane`（有尾翼），不要选 Flying Wing。
- X-Plane 机型选带 elevon/V-tail 的模型。
- INAV 输出 aileron/elevator/rudder 三个逻辑轴，X-Plane 机型自己做混控。
- 这样虽然“混控在 X-Plane”，但飞行姿态和 INAV 的稳定回路是正确的。

**不要做的事：**

- 不要在 `scripts/hid2msp.py` 里做 elevon 混控再送给 INAV；INAV 的 Mixer 会再混一次。
- 不要在 INAV 选 Flying Wing 的同时，又用标准 X-Plane 桥的 `S03-02,S01-03` 映射；会双重混控。

### 4.7 优缺点

**优点：**

- 手柄真正像 MSP 接收机：16 通道、按键、可扩展。
- 不依赖 X-Plane 的 Cowl Flap 轴 hack。
- 可以和 HITL 插件、OSD、传感器注入一起用。
- 桥很小，方便改成 CRSF/SBUS/MAVLink。

**缺点：**

- 需要跑一个 Python 进程；pygame 对某些手柄的轴编号要做适配。
- HITL 插件只回传 4 个控制轴，INAV 混控仍然不会出现在 X-Plane 的每个舵面上。
- 三个 TCP 客户端要规划好 UART，不能让两个客户端抢同一个端口。

---

## 5. 方案 C：把 INAV 的每个舵面输出真正送进 X-Plane

只有这个方案能同时做到：

- 手柄 → INAV（MSP RX）；
- INAV 内部做 elevon/V-tail 混控；
- X-Plane 里的左右舵面分别跟随 INAV 的 S1/S2 输出。

### 5.1 原理

1. `scripts/hid2msp.py` 继续向 SITL 的 UART3 发 `MSP_SET_RAW_RC`。
2. 新写一个 `servo2xplane.py`（或 X-Plane 插件），向 SITL 的另一个 UART 发 MSP 请求：
   - `MSP_SERVO`（103）：读每个舵机输出；
   - `MSP_MOTOR`（104）：读电机输出。
3. 把 S1/S2 映射成 X-Plane 的左右 elevon datarefs，把 S3/S4 映射成 V-tail 舵面，把 M1 映射成油门。
4. 设置 `sim/operation/override/override_control_surfaces = 1`，用 UDP `DREF` 写：
   - `sim/flightmodel/controls/ail1def`
   - `sim/flightmodel/controls/ail2def`
   - `sim/flightmodel/controls/elv1def`
   - `sim/flightmodel/controls/elv2def`
   - `sim/flightmodel/controls/rud1def`
   - `sim/flightmodel/controls/rud2def`

具体 dataref 取决于机型。最稳的做法是做一个自定义 X-Plane 机型，把左右 elevon 分别绑定到 `elv1def`/`elv2def` 或 `ail1def`/`ail2def`，然后用 `override_control_surfaces` 接管。

### 5.2 最小实现草图

```python
# 伪代码：50 Hz
servos = msp_request(103)          # 读 S1..Sn
motors = msp_request(104)          # 读 M1..
send_dref("sim/operation/override/override_control_surfaces", 1)
send_dref("sim/flightmodel/controls/elv1def", scale(servos[0]))
send_dref("sim/flightmodel/controls/elv2def", scale(servos[1]))
send_dref("sim/cockpit2/engine/actuators/throttle_ratio_all", scale(motors[0]))
```

X-Plane `DREF` UDP 包格式：

```text
"DREF" + float32(value) + dataref 字符串 + '\0' + 补齐
```

发到 X-Plane 的 `Port we receive on`（通常是 49000/49001）。

### 5.3 难度与风险

- 需要知道每个机型的舵面 dataref，不是即插即用。
- 需要处理符号、行程、中立点、延迟；调不好会抖。
- 需要自己写第二个 MSP 客户端，且和 Configurator/插件抢 UART。
- 更适合“验证 INAV 混控算法”的研发场景，不适合第一次上手。

如果你只是想让飞机在 X-Plane 里飞得对，**不要做 C**；用 A 或 B 的“X-Plane 侧混控”即可。

---

## 6. 方案 D：ArduPilot SITL（如果 INAV 的限制不能接受）

ArduPilot 的 X-Plane SITL 已经内置了“摇杆 → RC 通道”和“每个 servo 输出 → X-Plane dataref”的 JSON 映射：

- X-Plane 只需要在 `Settings → Data Output` 里启用一路 UDP 输出，端口 49001；
- SITL 监听 49001，向 X-Plane 的 49000 发命令；
- `xplane_plane.json` 定义：
  - 摇杆轴/按键 → RC 通道；
  - servo 输出 → X-Plane 舵面 datarefs。
- 因此，**ArduPilot 的 elevon/V-tail 混控可以真实地出现在 X-Plane 里**，而且手柄直接由 X-Plane 读取，不需要写桥。

快速命令（需要 ArduPilot 构建环境）：

```bash
cd ardupilot
./waf configure --board sitl
./waf plane
cd ArduPlane
sim_vehicle.py -D -f xplane --console --map
```

优点：

- 官方支持，成熟；
- 摇杆、按键、混控、舵面映射都是一等公民；
- 不需要自己写 MSP 桥。

缺点：

- 换了一套固件和参数体系；
- macOS 上需要编译/安装 MAVProxy、pymavlink；
- 不是 INAV，之前的 INAV 配置不能直接复用。

参考：<https://ardupilot.org/dev/docs/sitl-with-xplane.html>

---

## 7. 选型建议（决策树）

```text
你要的是“在 X-Plane 里用手柄飞，INAV 在环”吗？
├─ 是 → 方案 A
│      └─ 发现手柄按键不够 / 想要 16 通道 / 想接 HITL 插件？
│             └─ 方案 B（混控仍交给 X-Plane 机型）
└─ 你要验证 INAV 自己的 elevon/V-tail 混控吗？
       ├─ 只在 Configurator 看 → 方案 B + Servo 页
       └─ 一定要在 X-Plane 里看 → 方案 C
              └─ 不想写桥 → 方案 D（ArduPilot）
```

---

## 8. macOS 专属坑与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| SITL 打不开：`bad CPU type` | 二进制架构不匹配 | 用 universal 版；Apple Silicon 装 Rosetta |
| SITL 被 Gatekeeper 拦截 | 未签名/隔离属性 | `xattr -dr com.apple.quarantine` |
| X-Plane 插件不加载 | 插件被 quarantine | `xattr -rd com.apple.quarantine .../mac.xpl` |
| SITL 一直 `Waiting for connection...` | 端口不一致 / 防火墙 / 缺少 XITL dataref | 确认 X-Plane receive 端口 = `--simport`；允许 UDP；试 49000/49001；仍不行则装 INAV-X-Plane-XITL 插件，或改用 HITL 插件的 SITL 连接模式 |
| Configurator 连不上 | 5760 被占用 / SITL 没启动 | `lsof -nP -iTCP:5760`；重启 SITL |
| 手柄在 X-Plane 里没反应 | macOS 输入监控 / 未校准 | 系统设置 → 隐私与安全 → 输入监控；X-Plane 里校准 |
| pygame 找不到手柄 | SDL2 不识别 / 权限 | `python3 scripts/hid2msp.py --list`；换 USB/蓝牙；给 Terminal 输入监控 |
| 通道方向反了 | X-Plane 轴方向 / INAV 通道方向 | 只在一处反向；先在 Receiver 页确认 |
| 混控动作怪异 | INAV Flying Wing + X-Plane 又混一次 | 改 INAV 为 Airplane，或做方案 C |
| HITL 插件连不上 SITL | 端口被 Configurator 占用 | Configurator 5760、插件 5761、桥 5762 |
| 桥一停飞机就失控 | 没配 failsafe | INAV Failsafe 设 `DROP`/`RTH`；先地面测试 |

---

## 9. 验收清单

- [ ] `inav_SITL --help` 能运行，显示 `INAV 9.0.0 SITL`。
- [ ] Configurator 能通过 TCP 连上 SITL。
- [ ] Receiver 页能看到 CH1–CH8（方案 A）或 CH1–CH16（方案 B）。
- [ ] 摇杆方向正确：右打杆 → roll 右、拉杆 → pitch 上、油门向上推。
- [ ] 端点约 1000–2000 µs，中位 1500 µs。
- [ ] ARM 开关能解锁/上锁；ANGLE/HORIZON 能切换。
- [ ] Servo 页能看到预期的混控（Flying Wing 的 S1/S2 反向联动）。
- [ ] X-Plane 里舵面方向正确，没有双重混控。
- [ ] 关掉手柄桥/拔掉手柄，INAV 进入 failsafe（地面测试）。
- [ ] 连续飞 10 分钟，TCP 不掉线，X-Plane 不卡顿。

---

## 10. 参考

- INAV SITL 文档：<https://github.com/iNavFlight/inav/blob/master/docs/SITL/SITL.md>
- INAV X-Plane 文档：<https://github.com/iNavFlight/inav/blob/master/docs/SITL/X-Plane.md>
- INAV SITL X-Plane 源码：<https://github.com/iNavFlight/inav/blob/master/src/main/target/SITL/sim/xplane.c>
- INAV MSP `SET_RAW_RC`：<https://github.com/iNavFlight/inav/blob/master/src/main/fc/fc_msp.c>
- INAV SITL 串口/TCP：<https://github.com/iNavFlight/inav/blob/master/src/main/drivers/serial_tcp.c>
- INAV-X-Plane-HITL：<https://github.com/RomanLut/INAV-X-Plane-HITL>
- HITL v1.5.0（含 macOS 插件）：<https://github.com/RomanLut/INAV-X-Plane-HITL/releases/tag/v1.5.0>
- ArduPilot X-Plane SITL：<https://ardupilot.org/dev/docs/sitl-with-xplane.html>
- X-Plane 11 Demo：<https://www.x-plane.com/desktop/try-it/older/>
- pygame：<https://www.pygame.org/>

---

## 附录 A：本仓库里的文件

| 文件 | 用途 |
|---|---|
| `scripts/hid2msp.py` | HID 手柄 → MSP `SET_RAW_RC` 桥 |
| `config/hid2msp.example.json` | 手柄轴/按键映射示例 |
| `3rdparty/inav-configurator/resources/public/sitl/macos/inav_SITL` | macOS universal SITL 二进制 |
| `INAV-X-Plane-HITL/` | X-Plane HITL 插件源码/文档 |

## 附录 B：最小 MSP 帧示例

16 通道，全部 1500（中位），油门 1000：

```python
import struct
ch = [1500, 1500, 1000, 1500] + [1500] * 12
payload = struct.pack("<16H", *ch)
body = bytes([len(payload), 200]) + payload
cs = 0
for b in body:
    cs ^= b
frame = b"$M<" + body + bytes([cs])
```

把这 38 字节发到 SITL 的 MSP UART TCP 端口即可。`scripts/hid2msp.py` 做的就是这件事，外加手柄读取、死区、反向、按键切换和断线重连。

---

## 附录 C：INAV-X-Plane-HITL 在 macOS 上的适配评估

### C.1 结论

`INAV-X-Plane-HITL` **不是“从零移植到 macOS”**：源码里已经有 `APL` 分支、`mac64` Makefile 目标、macOS SDK 框架和 GitHub Actions 的 `macos-13` 构建任务。真正要做的是“编译 + 安装 + Gatekeeper 处理 + 在 X-Plane 里联调”。

- **X-Plane 11（Intel 或 Apple Silicon + Rosetta）**：约 **0.5–1 人日**；纯编译约 15 分钟，代码改动基本为 0。
- **X-Plane 12 原生 arm64 / Universal**：约 **2–5 人日**，主要工作在替换 x86_64-only 的 XPLM/XPWidgets SDK、改 Makefile 架构、双架构测试。
- **和 INAV 9 SITL 联调**：另加 **0.5–2 人日**，取决于 `MSP_SIMULATOR` 协议是否要改。

### C.2 本机实测（macOS 26.3.1 arm64）

在仓库的 `src/` 下直接执行：

```bash
make mac64
```

结果：

- **13 秒**完成 clean build；
- **0 error**，51 个 warning（主要是 OpenGL/GLUT/OpenAL 弃用、`sprintf`、`kCFURLHFSPathStyle`）；
- 产物 `release/.../64/mac.xpl`，约 **510 KB**，`Mach-O 64-bit dynamically linked shared library x86_64`；
- 导出 `_XPluginStart` / `_XPluginStop` / `_XPluginEnable` / `_XPluginDisable`；
- 链接 `XPLM`、`XPWidgets`、`OpenGL`、`GLUT`、`OpenAL`、`CoreFoundation`，都是 X-Plane 11 自带/系统框架；
- 不需要 Homebrew 的 GTK3/OpenAL 也能编译；`pkg-config gtk+-3.0` 的报错只是 Makefile 噪声。

> 注意：以上编译验证针对临时构建产物；后续已把 `release/` 里的 `mac.xpl` 安装到 X-Plane 11.55r2，并成功加载出插件菜单。临时构建产物本身没有单独在 X-Plane 里加载测试。

### C.3 现有 release 里的 mac.xpl

`release/Aircraft/Extra Aircraft/NK_FPVSurfwing/plugins/INAV-X-Plane-HITL/64/mac.xpl` 已经存在：

- x86_64；
- 624 KB；
- 导出 XPlugin 入口；
- 依赖 XPLM/XPWidgets/OpenGL/GLUT/OpenAL。

所以如果只是 **X-Plane 11 + macOS（Intel 或 Rosetta）**，可以先直接用这个预编译文件，适配工作主要是：

1. 把 `Aircraft/Extra Aircraft/NK_FPVSurfwing` 复制到 X-Plane 11 的 `Aircraft/Extra Aircraft/`；
2. 去掉 quarantine：
   ```bash
   xattr -rd com.apple.quarantine ".../NK_FPVSurfwing/plugins/INAV-X-Plane-HITL/64/mac.xpl"
   xattr -rd com.apple.quarantine ".../NK_FPVSurfwing/plugins/xlua/64/mac.xpl"
   ```
3. 在 X-Plane 里勾选 “Show extra aircraft from older versions”，加载 INAV Surfwing；
4. 用 `Plugins → INAV HITL/SITL → Connect to SITL` 连 `127.0.0.1:5761`；
5. 检查 OSD、传感器、舵面。

### C.4 各目标的工作量

| 目标 | 需要做什么 | 估计 |
|---|---|---|
| 用 release 的 mac.xpl 跑 X-Plane 11 | 解压、放 Aircraft、去 quarantine、加载、连 SITL | **0.5–2 小时** |
| 从源码重建 X-Plane 11 插件 | `make mac64`、替换 `mac.xpl`、联调 | **0.5–1 人日**（编译 15 分钟） |
| X-Plane 12 原生 arm64 | 换 universal/arm64 的 XPLM/XPWidgets SDK；Makefile 去掉 `-m64`、改 `-arch arm64 -arch x86_64`；双架构测试 | **2–5 人日** |
| X-Plane 12 先跑 Rosetta | 用现有 x86_64 插件，X-Plane.app 勾选 “Open using Rosetta” | **0.5–1 小时**（性能下降） |
| INAV 9 SITL 协议联调 | 验证 `MSP_SIMULATOR`（0x201F）版本 2、传感器结构、OSD 数据 | **0.5–2 人日** |
| 更多 macOS USB 串口 | `msp.cpp` 目前只枚举 `cu.usbmodem*`；补 `cu.usbserial*`、`cu.wchusbserial*`、`cu.SLAB_USBtoUART*` | **0.5 人日** |
| 签名/公证分发 | `codesign`、`notarytool`、stapling | **1–2 人日** |

### C.5 如果要做 arm64/Universal，具体改哪里

1. **SDK**：当前 `src/SDK/Libraries/Mac/XPLM.framework/XPLM` 和 `XPWidgets.framework/XPWidgets` 都是 **x86_64 only**。换成 X-Plane 12 SDK 里的 universal/arm64 版本，或从 X-Plane 12 安装目录复制。
2. **Makefile**：
   - 去掉 `-m64`（arm64 不认）；
   - 把 `-arch x86_64` 改成 `-arch x86_64 -arch arm64`，或新增 `macarm64` / `macuniversal` 目标；
   - 把 `-framework OpenAL` 换成 `-lopenal` + Homebrew include/lib（如果 Apple 的 OpenAL 在新系统上不可用）。
3. **代码**：
   - `kCFURLHFSPathStyle` 改 `kCFURLPOSIXPathStyle`（只是 deprecation，非必须）；
   - `sprintf` 改 `snprintf`（非必须）；
   - 检查 `#if APL` 分支里 `long`/指针宽度假设（目前看没有明显问题）。
4. **CI**：当前只有 `macos-13`（x86_64）。要加 `macos-14`/`macos-15` arm64 matrix，分别产出 x86_64 和 arm64，再用 `lipo` 合并。
5. **测试**：X-Plane 11 x86_64、X-Plane 12 arm64 各跑一遍；重点看 OSD 的 OpenGL 渲染、OpenAL 声音、串口/TCP 连接。

### C.6 建议的落地顺序

1. **先不动代码**：用 release 的 `mac.xpl` 在 X-Plane 11 里跑通 SITL 连接和 OSD（0.5–2 小时）。
2. 如果 release 版本和当前 INAV 9 不兼容：从源码 `make mac64` 重建，再联调（0.5–1 天）。
3. 如果确认要 X-Plane 12 原生 arm64：再做 SDK/Makefile 的 universal 改造（2–5 天）。
4. 如果只在 X-Plane 12 上用、且能接受 Rosetta：直接用 x86_64 插件 + Rosetta，省掉 arm64 改造。
