# scripts

| 脚本 | 用途 |
|---|---|
| `start_sitl.sh` | 启动 INAV SITL，读取 `config/runtime/plane.bin` |
| `start_bridge.sh` | 启动 `hid2msp.py`，读取 `config/hid2msp_inav.json` |
| `check_ports.sh` | 检查 5760/5761/5762/5763 |
| `hid2msp.py` | HID 手柄/遥控器 → MSP `SET_RAW_RC` 桥 |
| `calibrate_hid.py` | 交互式标定 AETR 轴，结果写入 `config/calibration.json` |

## 常用命令

```bash
# 终端 A
./scripts/start_sitl.sh

# 终端 B（先把 SWB 拨到低位）
./scripts/start_bridge.sh

# 检查端口
./scripts/check_ports.sh

# 标定摇杆
python3 scripts/calibrate_hid.py
```

`start_sitl.sh` 和 `start_bridge.sh` 会自动定位项目根目录，因此可以在任意目录执行。
