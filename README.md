# Gamepad for INAV SITL + X-Plane

![cross-platform](https://github.com/XinyiLiu577086410/Joystick-for-iNav-XPlane11-SITL/actions/workflows/cross-platform.yml/badge.svg?branch=cross-platform)

**当前分支：`cross-platform`**  
目标是用一套核心代码支持 Windows、macOS、Linux；平台的系统调用分别放在适配器中。

> `main` 是原 macOS 分支，`windows` 是原 Windows 分支，二者保留为参考实现，不再加新功能。

## 1. 组成

```text
X-Plane 11/12
  └─ HITL 插件（win.xpl / mac.xpl / lin.xpl）
       ↕ 5761
INAV SITL（inav_SITL）
  ├─ 5760 UART1：Configurator / CLI
  ├─ 5761 UART2：HITL 插件
  ├─ 5762 UART3：hidrx bridge（MSP RX）
  └─ 5763 UART4：MSP DisplayPort
```

## 2. 要求

- Python 3.10+
- `pygame`（手柄/标定需要）
- INAV Configurator 自带的 `inav_SITL`
- X-Plane 11/12 和 INAV HITL 插件
- Linux 键盘需要 X11；Wayland 只降级，不提供全局键盘

安装：

```bash
python -m pip install -e .
# 可选
python -m pip install pygame
```

未安装 entry point 时，所有命令都可用：

```bash
python -m hidrx.apps.cli ...
```

## 3. 首次配置

**没有默认手柄映射，也没有默认键位。** 必须手动跑一次：

```bash
hidrx setup gamepad
hidrx setup keyboard
```

### 手柄向导

依次检测：

- roll → CH1
- pitch → CH2
- throttle → CH3
- yaw → CH4
- 模式旋钮 → CH8（6 档）
- NAV WP 开关 → CH6（LOW/HIGH）
- arm 开关 → CH7（上锁/解锁位置）

写入配置并带上当前平台标识。

### 键盘向导

逐项捕获全部动作（横滚/俯仰/偏航/油门、解锁、模式 1–6、NAV WP），界面提示为中文；重复绑定会被拒绝。键名由当前平台解释，不做跨平台转换。

配置位置：

```text
config/hid2msp_inav.json          # 本机标定结果，不跨平台复用
config/runtime/<version>/plane.bin
config/runtime/<version>/meta.json
config/inav/<version>/minimal.txt
```

## 4. INAV 版本

```bash
hidrx inav list
hidrx inav use 10.0.0
hidrx inav check "C:\Program Files (x86)\INAV-Configurator_Win64_10.0.0"
```

启动时指定：

```bash
hidrx start --inav-version 10.0.0
hidrx start --inav-path "C:\Program Files (x86)\INAV-Configurator_Win64_10.0.0"
```

优先级：

1. `--inav-path`
2. `--inav-version`
3. `HIDRX_INAV_PATH` / `HIDRX_INAV_VERSION`
4. `config/runtime/inav.json` 的 active 版本
5. 自动选最高版本

每个版本使用独立 eeprom；`meta.json` 版本不匹配时拒绝启动。

## 5. 启动与停止

```bash
hidrx start                 # SITL + bridge
hidrx start sitl
hidrx start bridge
hidrx start --input auto
hidrx start --input gamepad
hidrx start --input keyboard

hidrx stop
hidrx restart
hidrx status
hidrx status --json
hidrx logs -n 100
hidrx logs -f
```

### 输入模式

| 模式 | 手柄掉线 | 手柄重连 |
|---|---|---|
| `auto` | 键盘已配置 → 回退键盘；否则暂停发 RC | 自动收回手柄 |
| `gamepad` | **暂停发 RC，bridge 不退出**，SITL failsafe | 立即恢复发 RC |
| `keyboard` | 不受影响 | 忽略手柄 |

所有模式都不会因为手柄拔掉而退出 bridge。

## 6. 配置加载与 eeprom

```bash
hidrx config load --inav-version 10.0.0
hidrx config load --file config/inav/10.0.0/minimal.txt --no-save

hidrx backup eeprom --name before-tune --inav-version 10.0.0
hidrx backups --version 10.0.0
hidrx restore eeprom before-tune --inav-version 10.0.0
hidrx reset --yes --inav-version 10.0.0
```

`config load` 通过 5760 发送 CLI 命令，可选 `save`。

## 7. Doctor

```bash
hidrx doctor
```

检查 platform、键盘能力、X-Plane、HITL 插件、INAV 安装/选择/eeprom、配置、启动门禁；失败返回非 0。

## 8. 从旧分支迁移

> 旧 `hidctl.py`、`hidctl.cmd`、`scripts/` 及旧 macOS 文档已从 `cross-platform` 分支移除；下表只用于从旧分支迁移。

旧 `hidctl` 命令对应关系：

| 旧 | 新 |
|---|---|
| `hidctl start` | `hidrx start` |
| `hidctl stop` / `restart` | `hidrx stop` / `restart` |
| `hidctl status` | `hidrx status` |
| `hidctl setup joystick` | `hidrx setup gamepad` |
| `hidctl setup keyboard` | `hidrx setup keyboard` |
| `hidctl backup eeprom` | `hidrx backup eeprom` |
| `hidctl restore eeprom NAME` | `hidrx restore eeprom NAME` |
| `hidctl config load` | `hidrx config load` |

迁移注意：

- `HIDCTL_SITL` **不再读取**；用 `--inav-path` 或 `HIDRX_INAV_PATH`。
- 旧 `hid2msp_inav.json` 没有 `platform` 字段，会被视为未配置；重新跑：
  ```bash
  hidrx setup gamepad
  hidrx setup keyboard
  ```
- 旧 `config/runtime/plane.bin` 不会自动迁移；按版本放到：
  ```text
  config/runtime/<version>/plane.bin
  ```

## 9. 架构

```text
apps/        hidrx CLI / bridge / setup
services/    INAV、SITL、bridge、status、doctor、eeprom
core/        MSP、通道、配置、KeyboardMapper、BridgeRunner
platform/    Windows / macOS / Linux 适配器
```

`core/` 和 `services/` 不出现平台判断；只有 `platform/factory.py` 选择实现。

## 10. 当前限制

- macOS 前台门禁依赖 `osascript` / System Events 权限；未在真实 macOS 验证。
- Linux Wayland 不提供全局键盘；请使用 X11。
- macOS/Linux 适配器尚未在真实机器上完整冒烟。
- 手柄模式档位目前要求一个 6 档旋钮轴，不支持多个按钮生成 CH8。
- 没有默认映射；配置不跨平台复用。

## 11. 安全

- 首次使用先确认电机未接桨或飞机固定；
- 先在 X-Plane 中测试通道方向和 failsafe；
- 不要把真实飞行器与 SITL 配置混用；
- `reset --yes` 会删除当前版本 eeprom，先备份。
