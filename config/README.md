# config

本目录放**人可编辑的配置源文件**；SITL 运行时真正读取的是 `runtime/plane.bin`。

| 文件 | 类型 | 谁读取 |
|---|---|---|
| `INAV_SITL_MINIMAL_NODEFAULTS.txt` | INAV CLI 源配置 | 人/Configurator CLI 手动加载 |
| `hid2msp_inav.json` | HID → RC 映射 | `scripts/hid2msp.py` 每次启动 |
| `hid2msp.example.json` | 通用示例 | 仅参考，不参与运行 |
| `runtime/plane.bin` | SITL eeprom | SITL 每次启动 `--path` 读取 |
| `runtime/backups/` | eeprom 备份 | `hidctl backup` / `reset` / `restore` 生成 |
| `calibration.json` | 标定结果（可选） | 人查看；由 `scripts/calibrate_hid.py` 生成 |

## 关键关系

```text
INAV_SITL_MINIMAL_NODEFAULTS.txt
        │ Configurator CLI 加载 + save
        ▼
runtime/plane.bin
        │ SITL 启动时 --path 读取
        ▼
INAV SITL 运行时配置
```

- 修改 `.txt` 不会自动影响运行中的 SITL；必须重新加载并 `save`。
- `runtime/plane.bin` 是二进制 eeprom，不要直接编辑。
- `runtime/` 和 `calibration.json` 已被 `.gitignore` 排除。
- 首次使用或 `runtime/plane.bin` 丢失时，SITL 会生成默认配置，需要重新加载 CLI。
