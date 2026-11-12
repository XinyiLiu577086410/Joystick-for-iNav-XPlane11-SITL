# config

本目录放**人可编辑的配置源文件**；SITL 运行时真正读取的是 `runtime/<version>/plane.bin`。

| 路径 | 类型 | 谁读取 |
|---|---|---|
| `inav/<version>/minimal.txt` | INAV CLI 源配置，按版本隔离 | `hidrx config load` / Configurator CLI |
| `hid2msp.example.json` | 空模板 | 仅参考，不参与运行 |
| `hid2msp_inav.json` | 本机标定结果（已忽略） | `hidrx setup` 生成，bridge 启动时读取 |
| `runtime/<version>/plane.bin` | SITL eeprom | SITL 启动时 `--path` 读取 |
| `runtime/<version>/meta.json` | eeprom 版本元数据 | `hidrx` 启动/doctor 校验 |
| `runtime/backups/<version>/` | eeprom 备份 | `hidrx backup/restore/reset` |
| `calibration.json` | 标定结果（可选，已忽略） | 人查看 |

## 关键关系

```text
config/inav/<version>/minimal.txt
        │ hidrx config load --inav-version <version>
        ▼
config/runtime/<version>/plane.bin
        │ SITL 启动时 --path 读取
        ▼
INAV SITL 运行时配置
```

- 修改 `.txt` 不会自动影响运行中的 SITL；必须重新 `config load`（默认会 `save`）。
- `plane.bin` 是二进制 eeprom，不要直接编辑。
- `runtime/`、`hid2msp_inav.json`、`calibration.json` 已被 `.gitignore` 排除。
- 没有默认 HID/键盘映射；首次使用先运行 `hidrx setup joystick` / `hidrx setup keyboard`。
- 旧版本的 `config/INAV_SITL_MINIMAL_NODEFAULTS.txt` 已迁移到 `config/inav/10.0.0/minimal.txt`。
