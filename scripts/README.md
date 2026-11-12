# scripts（legacy）

`hidctl.py` 和 `scripts/hid2msp.py` 已从 `cross-platform` 分支移除；新实现位于：

```text
src/hidrx/
```

新入口：

```bash
hidrx ...
# 或
python -m hidrx.apps.cli ...
```

本目录剩余文件是旧分支留下的独立工具/参考实现，**不被 `hidrx` 调用**：

| 文件 | 状态 |
|---|---|
| `keyboard_input.py` | 旧 Windows 键盘实现，仅参考 |
| `logpump.py` | 旧日志包装，仅参考 |
| `calibrate_hid.py` | 独立手柄标定脚本，未接入新 CLI |
| `msp_probe.py` | 独立 MSP 探测工具 |
| `msp_tap.py` | 独立 TCP tap 工具 |

需要新功能时不要再改这些文件，改 `src/hidrx/`。
