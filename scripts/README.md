# scripts

| 脚本 | 用途 |
|---|---|
| `start_xplane.sh` | 后台启动 X-Plane（已运行则跳过） |
| `start_sitl.sh` | 后台启动 INAV SITL，读取 `config/runtime/plane.bin` |
| `start_bridge.sh` | 后台启动 `hid2msp.py`，读取 `config/hid2msp_inav.json` |
| `stop_all.sh` | 停止 SITL + 手柄桥 |
| `restart_sitl.sh` | 软重置 SITL（保留 eeprom） |
| `status.sh` | 查看 PID + 端口 |
| `check_ports.sh` | 检查 5760/5761/5762/5763 |
| `hid2msp.py` | HID 手柄/遥控器 → MSP `SET_RAW_RC` 桥 |
| `calibrate_hid.py` | 交互式标定 AETR 轴，结果写入 `config/calibration.json` |

## 常用命令

```bash
# 三个后台脚本（无 stdout/stderr）
./scripts/start_xplane.sh
./scripts/start_sitl.sh
./scripts/start_bridge.sh

# 状态 / 端口
./scripts/status.sh
./scripts/check_ports.sh

# 停止 / 软重置
./scripts/stop_all.sh
./scripts/restart_sitl.sh

# 标定摇杆
python3 scripts/calibrate_hid.py
```

`start_sitl.sh` 和 `start_bridge.sh` 会自动定位项目根目录，因此可以在任意目录执行。
