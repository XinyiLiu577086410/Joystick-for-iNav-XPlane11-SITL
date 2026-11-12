# scripts

组件生命周期统一由仓库根目录的 `hidctl.cmd` / `hidctl.py` 管理，本目录只保留被它调用的程序和标定工具。

| 文件 | 用途 |
|---|---|
| `hid2msp.py` | HID 手柄/遥控器或键盘 → MSP `SET_RAW_RC` 桥 |
| `logpump.py` | 给 SITL/bridge 输出加时间戳、记录退出码、维护 PID 文件 |
| `msp_probe.py` | 通过 MSP 读飞控状态 / 发送 RC 帧 |
| `msp_tap.py` | 用户态 TCP tap，记录插件 → SITL 的 MSP 流量 |
| `keyboard_input.py` | Windows 键盘读取（`GetAsyncKeyState`）、X-Plane 前台检测、组合键、键位映射与键盘通道生成 |
| `calibrate_hid.py` | 交互式标定 AETR 轴，结果写入 `config/calibration.json` |

首次安装必须运行 `.\hidctl.cmd setup joystick`（手柄）或 `.\hidctl.cmd setup keyboard`（键盘）；
生成的 `config/hid2msp_inav.json` 已被 `.gitignore` 排除，仓库不附带默认映射。

## 常用命令（在仓库根目录执行）

```powershell
.\hidctl.cmd start              # SITL + bridge
.\hidctl.cmd status
.\hidctl.cmd setup joystick       # 手柄轴/方向设置向导
.\hidctl.cmd setup keyboard     # 键盘键位/组合键设置向导
.\hidctl.cmd logs sitl -f
.\hidctl.cmd doctor
python scripts\hid2msp.py --keys
.\hidctl.cmd capture --seconds 180   # 抓插件 <-> SITL 的 MSP
.\hidctl.cmd unlock             # 清理残留 run\hidctl.lock
.\hidctl.cmd stop

.\hidctl.cmd backup eeprom --name before-pid
.\hidctl.cmd backups
.\hidctl.cmd restore eeprom <backup> --yes
.\hidctl.cmd reset eeprom --yes
```

标定摇杆：

```powershell
python scripts\calibrate_hid.py
```
