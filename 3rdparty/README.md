# 3rdparty

外部上游项目，**不纳入本仓库 Git**（见根目录 `.gitignore`）。本地保留这些目录只是为了安装/查源码方便。

| 目录 | 上游 | 用途 |
|---|---|---|
| `INAV-X-Plane-HITL/` | https://github.com/RomanLut/INAV-X-Plane-HITL | X-Plane HITL 插件 + INAV Surfwing 飞机；运行时用它的 `release/` |
| `inav/` | https://github.com/iNavFlight/inav | INAV 固件源码，查 MSP/SITL/混控实现 |
| `inav-configurator/` | https://github.com/iNavFlight/inav-configurator | Configurator 源码，查 SITL 启动参数/协议 |

如果目录不存在：

```bash
cd 3rdparty
git clone https://github.com/RomanLut/INAV-X-Plane-HITL.git
git clone https://github.com/iNavFlight/inav.git
git clone https://github.com/iNavFlight/inav-configurator.git
```

运行时真正需要的是：

- `3rdparty/INAV-X-Plane-HITL/release/Aircraft/Extra Aircraft/NK_FPVSurfwing`
- 已安装的 **INAV Configurator 9.x**（`hidctl` 自动探测 SITL 可执行文件）

`inav/` 和 `inav-configurator/` 只是源码参考，不参与运行。
