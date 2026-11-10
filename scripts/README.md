# scripts

组件生命周期统一由仓库根目录的 `hidctl` 管理，本目录只保留被它调用的程序和标定工具。

| 文件 | 用途 |
|---|---|
| `hid2msp.py` | HID 手柄/遥控器或键盘 → MSP `SET_RAW_RC` 桥 |
| `keyboard_input.py` | macOS 全局键盘读取、键位映射、键盘通道生成 |
| `calibrate_hid.py` | 交互式标定 AETR 轴，结果写入 `config/calibration.json` |

## 常用命令（在仓库根目录执行）

```bash
./hidctl start              # SITL + bridge
./hidctl status
./hidctl logs sitl -f
./hidctl doctor
python3 scripts/hid2msp.py --keys
./hidctl stop

./hidctl backup eeprom --name before-pid
./hidctl backups
./hidctl restore eeprom <backup> --yes
./hidctl reset eeprom --yes
```

标定摇杆：

```bash
python3 scripts/calibrate_hid.py
```
