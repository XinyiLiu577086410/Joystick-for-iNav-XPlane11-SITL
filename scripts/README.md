# scripts

组件生命周期统一由仓库根目录的 `hidctl.cmd` / `hidctl.py` 管理，本目录只保留被它调用的程序和标定工具。

| 文件 | 用途 |
|---|---|
| `hid2msp.py` | HID 手柄/遥控器或键盘 → MSP `SET_RAW_RC` 桥 |
| `logpump.py` | 给 SITL/bridge 输出加时间戳、记录退出码、维护 PID 文件 |
| `keyboard_input.py` | Windows 全局键盘读取（`GetAsyncKeyState`）、键位映射、键盘通道生成 |
| `calibrate_hid.py` | 交互式标定 AETR 轴，结果写入 `config/calibration.json` |

## 常用命令（在仓库根目录执行）

```powershell
.\hidctl.cmd start              # SITL + bridge
.\hidctl.cmd status
.\hidctl.cmd setup              # 手柄轴/方向设置向导
.\hidctl.cmd logs sitl -f
.\hidctl.cmd doctor
python scripts\hid2msp.py --keys
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
