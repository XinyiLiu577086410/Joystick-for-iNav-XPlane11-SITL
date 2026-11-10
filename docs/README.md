# docs

| 文件 | 内容 |
|---|---|
| `README-macos.md` | `main` 分支（macOS 实现）的完整说明，保留作参考 |
| `SOLUTION.md` | 方案调研（A/B/C/D）、MSP/SITL/HITL 协议事实、macOS 适配评估 |
| `architecture.png` | 系统架构图（macOS 时代绘制，端口/组件仍适用） |
| `startup.png` | 组件启动时序 |
| `sequence.png` | 运行时 50 Hz RC/传感器/控制时序 |
| `make_diagrams.py` | 重新生成三张图（需要 matplotlib） |

Windows 分支的说明在仓库根目录 [README.md](../README.md)。

重新生成图：

```powershell
python docs\make_diagrams.py
```
