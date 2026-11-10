#!/usr/bin/env python3
"""hidctl (Windows) - manage INAV SITL and the HID-to-MSP bridge.

This file is the Windows implementation.  The macOS implementation lives on
the ``main`` branch; the two are intentionally separate.

X-Plane and INAV Configurator are external tools: this script never launches
or stops them, it only inspects them (read-only) for ``status``/``doctor``.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

if sys.platform != "win32":
    sys.exit("hidctl.py is the Windows implementation; use the main branch on macOS.")

VERSION = "2.0.0"

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "run"
LOGS = ROOT / "logs"
CONFIG = ROOT / "config"
RUNTIME = CONFIG / "runtime"
BACKUPS = RUNTIME / "backups"
EEPROM = RUNTIME / "plane.bin"
HID_CONFIG = CONFIG / "hid2msp_inav.json"
BRIDGE = ROOT / "scripts" / "hid2msp.py"
LOGPUMP = ROOT / "scripts" / "logpump.py"
HIDCTL_LOG = LOGS / "hidctl.log"

PORTS = (5760, 5761, 5762, 5763)
COMPONENTS = ("sitl", "bridge")
PWM_MIN, PWM_MAX = 1000, 2000
KINDS = {"bipolar", "unipolar", "tri", "binary", "multi"}

sys.path.insert(0, str(ROOT / "scripts"))
if (ROOT / ".deps").is_dir():
    sys.path.insert(0, str(ROOT / ".deps"))
from keyboard_input import (  # noqa: E402
    DEFAULT_KEYS,
    input_available,
    resolve_keycode,
)

# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CTRL_BREAK_EVENT = 1

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.GenerateConsoleCtrlEvent.restype = wintypes.BOOL
kernel32.GetConsoleWindow.argtypes = []
kernel32.GetConsoleWindow.restype = wintypes.HWND
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL


def _open_process(pid: int, access: int) -> int | None:
    handle = kernel32.OpenProcess(access, False, pid)
    return handle or None


def pid_exists(pid: int) -> bool:
    """True if the PID is alive.  Never uses os.kill (which terminates on Windows)."""
    if pid <= 0:
        return False
    handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_name(pid: int) -> str:
    handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(4096)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name
        return ""
    finally:
        kernel32.CloseHandle(handle)


def process_path(pid: int) -> Path | None:
    handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(4096)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value)
        return None
    finally:
        kernel32.CloseHandle(handle)


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


kernel32.GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
]
kernel32.GetProcessTimes.restype = wintypes.BOOL


def process_creation_time(pid: int) -> float | None:
    """Process start time as a Unix timestamp (to detect PID reuse)."""
    handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not handle:
        return None
    try:
        creation = FILETIME()
        exit_time = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return ticks / 10_000_000 - 11_644_473_600
    finally:
        kernel32.CloseHandle(handle)


def pid_is_component(component: str, pid: int) -> bool:
    if not pid_exists(pid):
        return False
    created = read_pid_created(component)
    if created:
        actual = process_creation_time(pid)
        if actual is None or abs(actual - created) > 3.0:
            return False  # PID was reused by another process
    name = process_name(pid).lower()
    if not name:
        # Cannot inspect the process; trust our PID file.
        return True
    if component == "sitl":
        return name == "inav_sitl.exe"
    if component == "bridge":
        return name.startswith("python")
    return False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def err(message: str) -> None:
    print(f"hidctl: {message}", file=sys.stderr)
    audit(f"ERROR {message}")


def audit(message: str) -> None:
    """Append one timestamped line to logs\\hidctl.log (never raises)."""
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with HIDCTL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{now()} [{os.getpid()}] {message}\n")
    except OSError:
        pass


def display_path(path: Path) -> str:
    """Prefer .\\relative when the path is inside the current directory."""
    try:
        rel = os.path.relpath(path, Path.cwd())
        if rel.startswith(".."):
            return str(path)
        return rel if rel.startswith(".") else f".{os.sep}{rel}"
    except (OSError, ValueError):
        return str(path)


def ensure_dirs() -> None:
    for path in (RUN, LOGS, RUNTIME):
        path.mkdir(parents=True, exist_ok=True)


def pid_file(component: str) -> Path:
    return RUN / f"{component}.pid"


def log_file(component: str) -> Path:
    return LOGS / f"{component}.log"


def append_log_header(component: str, action: str) -> None:
    ensure_dirs()
    with log_file(component).open("ab") as fh:
        fh.write(f"\n===== {now()} {action} {component} =====\n".encode())


def append_log_line(component: str, line: str) -> None:
    ensure_dirs()
    with log_file(component).open("ab") as fh:
        fh.write(f"{now()} {line.rstrip(chr(10))}\n".encode())


def log_size(component: str) -> int:
    try:
        return log_file(component).stat().st_size
    except OSError:
        return 0


def read_new_log(component: str, offset: int) -> str:
    path = log_file(component)
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def read_pid(component: str) -> int | None:
    path = pid_file(component)
    try:
        first = path.read_text().splitlines()[0]
        return int(first.strip())
    except (FileNotFoundError, ValueError, OSError, IndexError):
        return None


def read_pid_created(component: str) -> float:
    """Process creation time stored next to the PID (0 if unknown)."""
    try:
        lines = pid_file(component).read_text().splitlines()
        return float(lines[1]) if len(lines) > 1 else 0.0
    except (FileNotFoundError, ValueError, OSError):
        return 0.0


def write_pid(component: str, pid: int) -> None:
    ensure_dirs()
    created = process_creation_time(pid) or 0.0
    pid_file(component).write_text(f"{pid}\n{created:.3f}\n")


def remove_pid(component: str) -> None:
    try:
        pid_file(component).unlink()
    except FileNotFoundError:
        pass


def component_running(component: str) -> tuple[bool, int | None]:
    pid = read_pid(component)
    if pid is None:
        return False, None
    if pid_is_component(component, pid):
        return True, pid
    remove_pid(component)
    return False, None


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_ports(ports: tuple[int, ...], timeout: float, pid: int | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(port_open(port) for port in ports):
            return True
        if pid is not None and not pid_exists(pid):
            return False
        time.sleep(0.2)
    return False


def _hidden_run(cmd: list[str], timeout: float = 8.0) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def netstat_rows() -> list[tuple[str, str, str, int]] | None:
    """Return (local, foreign, state, pid) rows, or None if netstat failed."""
    output = _hidden_run(["netstat", "-ano", "-p", "tcp"])
    if not output:
        return None
    rows: list[tuple[str, str, str, int]] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        try:
            rows.append((parts[1], parts[2], parts[3].upper(), int(parts[4])))
        except (ValueError, IndexError):
            continue
    return rows


def port_has_established(port: int) -> bool:
    rows = netstat_rows()
    if rows is None:
        return False
    suffix = f":{port}"
    return any(
        state == "ESTABLISHED" and (local.endswith(suffix) or foreign.endswith(suffix))
        for local, foreign, state, _pid in rows
    )


def bridge_connected(pid: int) -> bool | None:
    rows = netstat_rows()
    if rows is None:
        return None
    return any(
        state == "ESTABLISHED" and row_pid == pid and foreign.endswith(":5762")
        for _local, foreign, state, row_pid in rows
    )


def _running_pids(image_name: str) -> list[int]:
    output = _hidden_run(
        ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
        timeout=6.0,
    )
    pids: list[int] = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        parts = [item.strip('"') for item in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == image_name.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def untracked_sitl(our_pid: int | None) -> list[int]:
    """inav_SITL.exe processes that are not the one in run\\sitl.pid."""
    return [pid for pid in _running_pids("inav_SITL.exe") if pid != our_pid]


def untracked_bridge(our_pid: int | None) -> list[int]:
    """Python processes connected to 5762 that are not in run\\bridge.pid."""
    rows = netstat_rows() or []
    pids = {
        row_pid
        for _local, foreign, state, row_pid in rows
        if state == "ESTABLISHED" and foreign.endswith(":5762") and row_pid != our_pid
    }
    return sorted(
        pid for pid in pids if process_name(pid).lower().startswith("python")
    )


# ---------------------------------------------------------------------------
# SITL discovery
# ---------------------------------------------------------------------------
def _sitl_candidates() -> list[Path]:
    found: list[Path] = []

    def add(path: Path) -> None:
        try:
            if path.is_file() and path not in found:
                found.append(path)
        except OSError:
            pass

    env = os.environ.get("HIDCTL_SITL")
    if env:
        add(Path(env).expanduser())

    roots: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Programs")

    for root in roots:
        try:
            entries = [d for d in root.iterdir() if d.is_dir() and d.name.upper().startswith("INAV")]
        except OSError:
            continue
        for entry in entries:
            add(entry / "resources" / "sitl" / "windows" / "inav_SITL.exe")
            add(entry / "resources" / "app" / "resources" / "sitl" / "windows" / "inav_SITL.exe")
            for app_dir in entry.glob("app-*"):
                add(app_dir / "resources" / "sitl" / "windows" / "inav_SITL.exe")
            for child in entry.glob("*"):
                if child.is_dir():
                    add(child / "resources" / "sitl" / "windows" / "inav_SITL.exe")

    which = shutil.which("inav_SITL.exe")
    if which:
        add(Path(which))
    return found


def _path_version(path: Path) -> tuple[int, int, int]:
    best = (0, 0, 0)
    for match in re.findall(r"(\d+)\.(\d+)\.(\d+)", str(path)):
        best = max(best, (int(match[0]), int(match[1]), int(match[2])))
    return best


def find_sitl() -> Path | None:
    env = os.environ.get("HIDCTL_SITL")
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return path
    candidates = _sitl_candidates()
    if not candidates:
        return None
    return max(candidates, key=_path_version)


# ---------------------------------------------------------------------------
# Process lifecycle
# ---------------------------------------------------------------------------
def spawn(component: str, cmd: list[str]) -> int | None:
    """Start cmd under the log pump; return the child PID or None.

    The pump keeps running after hidctl exits, timestamps every output line,
    records the child's exit code, and writes/removes run\\<component>.pid.
    """
    ensure_dirs()
    log = log_file(component)
    append_log_header(component, "start")
    append_log_line(component, "$ " + " ".join(cmd))

    pid_path = pid_file(component)
    try:
        pid_path.unlink()
    except FileNotFoundError:
        pass

    pump_cmd = [
        sys.executable,
        "-u",
        str(LOGPUMP),
        "--log",
        str(log),
        "--pidfile",
        str(pid_path),
        "--cwd",
        str(ROOT),
        "--",
        *cmd,
    ]
    try:
        pump = subprocess.Popen(
            pump_cmd,
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=DETACHED_PROCESS,
            close_fds=True,
        )
    except OSError as exc:
        append_log_line(component, f"spawn failed: {exc}")
        audit(f"spawn {component} failed: {exc}")
        return None

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        pid = read_pid(component)
        if pid is not None:
            if pid_exists(pid):
                append_log_line(component, f"pid={pid}")
                audit(f"spawn {component} pid={pid} pump={pump.pid}")
                return pid
            break
        if pump.poll() is not None:
            break
        time.sleep(0.1)

    append_log_line(component, "spawn failed (no pid file)")
    audit(f"spawn {component} failed (pump exited)")
    return None


def _terminate(pid: int) -> bool:
    handle = _open_process(pid, PROCESS_TERMINATE)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def _taskkill(pid: int) -> None:
    _hidden_run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=10.0)


def stop_component(component: str) -> int:
    pid = read_pid(component)
    if pid is None:
        remove_pid(component)
        return 0
    if not pid_is_component(component, pid):
        remove_pid(component)
        return 0

    append_log_header(component, "stop")
    audit(f"stop {component} pid={pid}")
    # Ask politely first: CTRL_BREAK to the child's process group.  Without a
    # console there is nothing to signal, so go straight to taskkill.
    graceful = False
    if kernel32.GetConsoleWindow():
        graceful = bool(kernel32.GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid))

    deadline = time.monotonic() + (5.0 if graceful else 0.5)
    while time.monotonic() < deadline:
        if not pid_exists(pid):
            remove_pid(component)
            return 0
        time.sleep(0.1)

    _taskkill(pid)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not pid_exists(pid):
            remove_pid(component)
            return 0
        time.sleep(0.1)

    if pid_exists(pid):
        _terminate(pid)
    remove_pid(component)
    return 0


def start_sitl(wait: bool = True) -> int:
    ensure_dirs()
    running, _ = component_running("sitl")
    if running:
        return 0

    sitl = find_sitl()
    if sitl is None:
        err("SITL not found; install INAV Configurator or set HIDCTL_SITL")
        return 1
    if not sitl.is_file():
        err(f"SITL not found: {sitl}")
        return 1

    strays = untracked_sitl(None)
    if strays:
        err(
            "another inav_SITL.exe is already running: "
            + ", ".join(f"pid {pid}" for pid in strays)
            + " (not in run\\sitl.pid; stop it first)"
        )
        return 1

    busy = [port for port in PORTS if port_open(port)]
    if busy:
        err(
            "SITL ports already in use: "
            + ", ".join(str(p) for p in busy)
            + " (stop old SITL first)"
        )
        return 1

    RUNTIME.mkdir(parents=True, exist_ok=True)
    pid = spawn("sitl", [str(sitl), f"--path={EEPROM}"])
    if pid is None:
        err("failed to start SITL; see logs\\sitl.log")
        return 1

    if wait and not wait_ports((5760, 5761), 20.0, pid):
        err("SITL did not open 5760/5761; see logs\\sitl.log")
        stop_component("sitl")
        return 1
    if not pid_exists(pid):
        err("SITL exited during startup; see logs\\sitl.log")
        remove_pid("sitl")
        return 1
    audit(f"start sitl ok pid={pid}")
    return 0


def start_bridge(wait: bool = True) -> int:
    ensure_dirs()
    running, _ = component_running("bridge")
    if running:
        return 0

    strays = untracked_bridge(None)
    if strays:
        err(
            "another bridge is already connected to 5762: "
            + ", ".join(f"pid {pid}" for pid in strays)
            + " (not in run\\bridge.pid; stop it first)"
        )
        return 1

    sitl_running, _ = component_running("sitl")
    if not sitl_running:
        err("warning: SITL is not running; bridge will keep retrying 127.0.0.1:5762")
    elif not port_open(5762):
        err(
            "warning: 5762 is closed; SITL UART3 is not MSP yet. "
            "Load config\\INAV_SITL_MINIMAL_NODEFAULTS.txt in Configurator and save."
        )

    if not HID_CONFIG.is_file():
        err(f"HID config not found: {HID_CONFIG}")
        return 1
    if not BRIDGE.is_file():
        err(f"bridge script not found: {BRIDGE}")
        return 1

    pid = spawn(
        "bridge",
        [
            sys.executable,
            "-u",
            str(BRIDGE),
            "--config",
            str(HID_CONFIG),
            "--port",
            "5762",
            "-v",
        ],
    )
    if pid is None:
        err("failed to start bridge; see logs\\bridge.log")
        return 1

    if wait:
        time.sleep(2.0)
        if not pid_exists(pid):
            err("bridge exited immediately; see logs\\bridge.log")
            remove_pid("bridge")
            return 1
    audit(f"start bridge ok pid={pid}")
    return 0


def start_all() -> int:
    rc = start_sitl()
    if rc != 0:
        return rc
    rc = start_bridge()
    if rc != 0:
        err("bridge failed; stopping SITL to avoid a half-started stack")
        stop_component("sitl")
        return rc
    return 0


def stop_all() -> int:
    stop_component("bridge")
    stop_component("sitl")
    return 0


def cmd_start(component: str, verbose: bool = True, follow: bool = False) -> int:
    names = ["sitl", "bridge"] if component == "all" else [component]
    offsets = {name: log_size(name) for name in names}

    if component == "sitl":
        rc = start_sitl()
    elif component == "bridge":
        rc = start_bridge()
    else:
        rc = start_all()

    if verbose:
        for name in names:
            text = read_new_log(name, offsets[name]).strip()
            print(f"--- {name} startup log ---")
            print(text if text else "(no new output)")
        cmd_status(False)
    if follow:
        cmd_logs(component, True, 20)
    return rc


def cmd_stop(component: str, verbose: bool = True) -> int:
    names = ["bridge", "sitl"] if component == "all" else [component]
    for name in names:
        running, pid = component_running(name)
        stop_component(name)
        if verbose:
            if running and pid is not None:
                print(f"{name}: stopped (pid {pid})")
            else:
                print(f"{name}: not running")
    return 0


def cmd_restart(component: str, verbose: bool = True) -> int:
    if component == "sitl":
        rc = cmd_stop("sitl", verbose)
        if rc != 0:
            return rc
        return cmd_start("sitl", verbose, False)
    if component == "bridge":
        rc = cmd_stop("bridge", verbose)
        if rc != 0:
            return rc
        return cmd_start("bridge", verbose, False)
    rc = cmd_stop("all", verbose)
    if rc != 0:
        return rc
    return cmd_start("all", verbose, False)


# ---------------------------------------------------------------------------
# X-Plane / HITL detection (external; never managed)
# ---------------------------------------------------------------------------
def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _ = winreg.QueryValueEx(key, "SteamPath")
            roots.append(Path(str(value)))
    except (OSError, ImportError, ValueError):
        pass
    return roots


def _xplane_candidates() -> list[Path]:
    candidates: list[Path] = []
    for variable in ("XPLANE_PATH", "XPLANE_APP"):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value))
    for root in _steam_roots():
        candidates.append(root / "steamapps" / "common" / "X-Plane 11")
        candidates.append(root / "steamapps" / "common" / "X-Plane 12")
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates.append(Path(base) / "X-Plane 11")
            candidates.append(Path(base) / "X-Plane 12")
    candidates.append(Path("C:/X-Plane 11"))
    candidates.append(Path("C:/X-Plane 12"))

    result: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        try:
            key = str(item.resolve())
        except OSError:
            key = str(item)
        if key not in seen and item.exists():
            seen.add(key)
            result.append(item)
    return result


def _file_version(path: Path) -> str | None:
    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.UINT),
        ]
        version.VerQueryValueW.restype = wintypes.BOOL

        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return None

        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(
            buffer, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)
        ):
            return None
        words = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD))
        language, codepage = words[0], words[1]

        query = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\FileVersion"
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(
            buffer, query, ctypes.byref(pointer), ctypes.byref(length)
        ):
            return None
        return str(ctypes.wstring_at(pointer.value)).strip() or None
    except (OSError, ValueError):
        return None


def _log_version(root: Path) -> str | None:
    try:
        with (root / "Log.txt").open("r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
    except OSError:
        return None
    match = re.search(r"X-Plane\s+(\S+)", first)
    return match.group(1) if match else None


def xplane_info() -> dict:
    pids = _running_pids("X-Plane.exe")
    pid = pids[0] if pids else None

    exe: Path | None = None
    if pid is not None:
        exe = process_path(pid)
    if exe is None:
        for candidate in _xplane_candidates():
            if candidate.is_file() and candidate.name.lower() == "x-plane.exe":
                exe = candidate
                break
            if candidate.is_dir() and (candidate / "X-Plane.exe").is_file():
                exe = candidate / "X-Plane.exe"
                break

    version = _file_version(exe) if exe is not None else None
    root = exe.parent if exe is not None else None
    if version is None and root is not None:
        version = _log_version(root)

    return {
        "external": True,
        "managed": False,
        "running": pid is not None,
        "pid": pid,
        "version": version,
        "path": str(exe) if exe is not None else None,
        "root": str(root) if root is not None else None,
    }


def _hitl_candidates(xp: dict) -> list[Path]:
    roots: list[Path] = []
    if xp.get("root"):
        roots.append(Path(xp["root"]))
    for candidate in _xplane_candidates():
        if candidate.is_dir() and candidate.name.lower() != "x-plane.exe":
            roots.append(candidate)

    patterns = (
        "Aircraft/Extra Aircraft/NK_FPVSurfwing/plugins/INAV-X-Plane-HITL/64/win.xpl",
        "Aircraft/Extra Aircraft/*/plugins/INAV-X-Plane-HITL/64/win.xpl",
        "Aircraft/*/plugins/INAV-X-Plane-HITL/64/win.xpl",
    )
    found: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for pattern in patterns:
            try:
                matches = list(root.glob(pattern))
            except OSError:
                matches = []
            for path in matches:
                key = str(path)
                if key not in seen and path.is_file():
                    seen.add(key)
                    found.append(path)
    return found


def _hitl_version(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        data = path.read_bytes()
        matches = re.findall(rb"V(\d+\.\d+\.\d+)", data)
        if matches:
            return matches[-1].decode("ascii", errors="replace")
    except OSError:
        pass
    return None


def hitl_info(xp: dict | None = None) -> dict:
    if xp is None:
        xp = xplane_info()
    paths = _hitl_candidates(xp)
    path = paths[0] if paths else None
    return {
        "external": True,
        "installed": path is not None,
        "version": _hitl_version(path),
        "path": str(path) if path is not None else None,
        "connected": port_has_established(5761),
    }


def _hitl_label(info: dict) -> str:
    if not info.get("installed"):
        return "plugin not found"
    version = info.get("version") or "version unknown"
    link = "connected" if info.get("connected") else "disconnected"
    return f"installed v{version}  link: {link}"


def _xplane_label(info: dict) -> str:
    version = info.get("version") or "version unknown"
    if info.get("running"):
        return f"running {version}  pid {info.get('pid')}"
    if info.get("path"):
        return f"installed {version}  (not running)"
    return "not found"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def status_data() -> dict:
    sitl_running, sitl_pid = component_running("sitl")
    bridge_running, bridge_pid = component_running("bridge")

    connected = None
    if bridge_running and bridge_pid is not None:
        connected = bridge_connected(bridge_pid)

    eeprom = {
        "path": str(EEPROM),
        "exists": EEPROM.is_file(),
        "size": EEPROM.stat().st_size if EEPROM.is_file() else None,
        "mtime": (
            datetime.fromtimestamp(EEPROM.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            if EEPROM.is_file()
            else None
        ),
    }
    xp = xplane_info()
    sitl = find_sitl()
    stray_sitl = untracked_sitl(sitl_pid if sitl_running else None)
    stray_bridge = untracked_bridge(bridge_pid if bridge_running else None)
    return {
        "platform": "windows",
        "sitl": {
            "running": sitl_running,
            "pid": sitl_pid,
            "ports": {str(port): port_open(port) for port in PORTS},
            "binary": str(sitl) if sitl else None,
        },
        "bridge": {
            "running": bridge_running,
            "pid": bridge_pid,
            "target": "127.0.0.1:5762",
            "connected": connected,
        },
        "stray": {
            "sitl": [
                {"pid": pid, "name": process_name(pid) or "?"} for pid in stray_sitl
            ],
            "bridge": [
                {"pid": pid, "name": process_name(pid) or "?"} for pid in stray_bridge
            ],
        },
        "eeprom": eeprom,
        "config": str(HID_CONFIG),
        "xplane": xp,
        "hitl": hitl_info(xp),
    }


def cmd_status(as_json: bool) -> int:
    data = status_data()

    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        sitl = data["sitl"]
        if sitl["running"]:
            open_ports = [p for p, is_open in sitl["ports"].items() if is_open]
            print(
                f"sitl    running  pid {sitl['pid']}  ports "
                + (",".join(open_ports) if open_ports else "none")
            )
        else:
            print("sitl    stopped")

        bridge = data["bridge"]
        if bridge["running"]:
            if bridge["connected"] is True:
                state = "connected"
            elif bridge["connected"] is False:
                state = "waiting"
            else:
                state = "unknown"
            print(f"bridge  running  pid {bridge['pid']}  target {bridge['target']}  {state}")
        else:
            print("bridge  stopped")

        eeprom = data["eeprom"]
        if eeprom["exists"]:
            print(f"eeprom  {display_path(EEPROM)}  ({eeprom['size']} bytes, {eeprom['mtime']})")
        else:
            print(f"eeprom  {display_path(EEPROM)}  (missing)")

        print(f"config  {display_path(HID_CONFIG)}")
        print(f"xplane  {_xplane_label(data['xplane'])}  (external, not managed)")
        print(f"hitl    {_hitl_label(data['hitl'])}  (X-Plane plugin)")

        for item in data["stray"]["sitl"]:
            print(
                f"stray   pid {item['pid']}  {item['name']}  "
                "(inav_SITL not managed by this hidctl)"
            )
        for item in data["stray"]["bridge"]:
            print(
                f"stray   pid {item['pid']}  {item['name']}  "
                "(connected to 5762, not managed by this hidctl)"
            )

    ok = (
        data["sitl"]["running"]
        and data["bridge"]["running"]
        and data["bridge"]["connected"] is not False
    )
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
def tail_lines(path: Path, count: int) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    return lines[-count:] if count > 0 else lines


def cmd_logs(component: str, follow: bool, lines: int) -> int:
    names = ["sitl", "bridge", "hidctl"] if component == "all" else [component]
    paths = [log_file(name) for name in names]

    if follow:
        existing = [path for path in paths if path.is_file()]
        if not existing:
            err("no log files yet")
            return 1
        for path in existing:
            print(f"==> {path} <==")
            for line in tail_lines(path, lines):
                print(line.rstrip("\n"))
        handles = []
        for path in existing:
            handle = path.open("r", encoding="utf-8", errors="replace")
            handle.seek(0, os.SEEK_END)
            handles.append(handle)
        print("(following; Ctrl-C to stop)")
        try:
            while True:
                moved = False
                for handle in handles:
                    chunk = handle.read()
                    if chunk:
                        sys.stdout.write(chunk)
                        sys.stdout.flush()
                        moved = True
                if not moved:
                    time.sleep(0.3)
        except KeyboardInterrupt:
            print()
        finally:
            for handle in handles:
                handle.close()
        return 0

    missing = False
    for path in paths:
        print(f"==> {path} <==")
        if not path.is_file():
            print("(missing)")
            missing = True
            continue
        for line in tail_lines(path, lines):
            print(line.rstrip("\n"))
        print()
    return 1 if missing and all(not path.is_file() for path in paths) else 0


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
def safe_label(label: str | None) -> str:
    if not label:
        return ""
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-")
    return f"-{value}" if value else ""


def backup_eeprom(label: str | None = None, quiet: bool = False) -> Path | None:
    if not EEPROM.is_file():
        err(f"eeprom not found: {EEPROM}")
        return None

    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"plane-{stamp}{safe_label(label)}"
    target = BACKUPS / f"{base}.bin"
    counter = 1
    while target.exists():
        target = BACKUPS / f"{base}-{counter:02d}.bin"
        counter += 1

    if not quiet:
        running, _ = component_running("sitl")
        if running:
            err("warning: live eeprom snapshot; avoid saving config at the same time")
    shutil.copyfile(EEPROM, target)
    audit(f"backup eeprom {target}")
    return target


def cmd_backup(label: str | None) -> int:
    path = backup_eeprom(label)
    if path is None:
        return 1
    print(path)
    return 0


def cmd_backups() -> int:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (p for p in BACKUPS.glob("plane-*.bin") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        print("no backups")
        return 0

    print(f"{'TIME':20} {'SIZE':>8}  NAME")
    for path in files:
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{mtime:20} {path.stat().st_size:>7}  {path.name}")
    return 0


def resolve_backup(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        candidate = Path.cwd() / path
        if candidate.exists():
            return candidate.resolve()
        candidate = ROOT / path
        if candidate.exists():
            return candidate.resolve()
        return path
    return path


def cmd_restore(file: str, yes: bool, no_start: bool, no_backup: bool) -> int:
    if not yes:
        err("restore is destructive; pass --yes")
        return 2

    source = resolve_backup(file)
    if not source.is_file():
        err(f"backup not found: {file}")
        return 1
    if EEPROM.exists() and source.resolve() == EEPROM.resolve():
        err("source is the current eeprom; choose a backup file")
        return 1

    stop_all()
    previous = None
    if not no_backup and EEPROM.is_file():
        previous = backup_eeprom("before-restore", quiet=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, EEPROM)

    print(f"restored: {source} -> {EEPROM}")
    audit(f"restore eeprom {source} -> {EEPROM}")
    if previous:
        print(f"previous eeprom saved: {previous}")

    if no_start:
        return 0
    return start_all()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------
def cmd_reset(no_backup: bool, yes: bool) -> int:
    if not yes:
        err("reset eeprom is destructive; pass --yes")
        return 2

    stop_all()
    backup = None
    if not no_backup and EEPROM.is_file():
        backup = backup_eeprom("before-reset", quiet=True)
    try:
        EEPROM.unlink()
    except FileNotFoundError:
        pass

    rc = start_sitl()
    print(f"eeprom reset: {EEPROM}")
    if backup:
        print(f"backup: {backup}")
    else:
        print("backup: none")
    print(
        "next: Configurator -> TCP 127.0.0.1:5760 -> CLI -> paste "
        "config\\INAV_SITL_MINIMAL_NODEFAULTS.txt -> save"
    )
    print("then: hidctl.cmd start bridge")
    return rc


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
def _check_channel(channel: int, where: str, errors: list[str]) -> None:
    if not isinstance(channel, int) or not 1 <= channel <= 16:
        errors.append(f"{where}: channel must be 1..16")


def _check_pwm(value: int, where: str, errors: list[str]) -> None:
    if not isinstance(value, int) or not PWM_MIN <= value <= PWM_MAX:
        errors.append(f"{where}: PWM must be {PWM_MIN}..{PWM_MAX}")


def validate_config(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"config not found: {path}"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot parse JSON: {exc}"]

    if not isinstance(data, dict):
        return ["top-level JSON must be an object"]

    port = data.get("port", 5762)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        errors.append("port must be 1..65535")
    rate = data.get("rate_hz", 50)
    if not isinstance(rate, (int, float)) or rate <= 0:
        errors.append("rate_hz must be > 0")

    channels: dict[int, str] = {}

    def claim(channel: int, where: str) -> None:
        _check_channel(channel, where, errors)
        if isinstance(channel, int):
            if channel in channels:
                errors.append(f"{where}: channel {channel} already used by {channels[channel]}")
            else:
                channels[channel] = where

    for index, item in enumerate(data.get("axes", []) or []):
        where = f"axes[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not isinstance(item.get("axis"), int) or item.get("axis", -1) < 0:
            errors.append(f"{where}: axis must be >= 0")
        claim(item.get("channel"), where)
        kind = item.get("kind", "bipolar")
        if kind not in KINDS:
            errors.append(f"{where}: kind must be one of {sorted(KINDS)}")
        trim = item.get("trim", 1500)
        _check_pwm(trim, f"{where}.trim", errors)
        if kind == "multi":
            levels = item.get("levels", 6)
            values = item.get("values", [])
            if not isinstance(levels, int) or levels < 2:
                errors.append(f"{where}: levels must be >= 2")
            if not isinstance(values, list) or len(values) != levels:
                errors.append(f"{where}: values length must equal levels")
            else:
                for value in values:
                    _check_pwm(value, f"{where}.values", errors)

    for index, item in enumerate(data.get("buttons", []) or []):
        where = f"buttons[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not isinstance(item.get("button"), int) or item.get("button", -1) < 0:
            errors.append(f"{where}: button must be >= 0")
        claim(item.get("channel"), where)
        _check_pwm(item.get("low", PWM_MIN), f"{where}.low", errors)
        _check_pwm(item.get("high", PWM_MAX), f"{where}.high", errors)

    for index, item in enumerate(data.get("buttons3", []) or []):
        where = f"buttons3[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be an object")
            continue
        claim(item.get("channel"), where)
        for key in ("low", "mid", "high"):
            if key in item:
                _check_pwm(item[key], f"{where}.{key}", errors)

    for index, item in enumerate(data.get("combine", []) or []):
        where = f"combine[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be an object")
            continue
        claim(item.get("channel"), where)
        for key in ("a", "b"):
            value = item.get(key)
            if not isinstance(value, int) or not 1 <= value <= 16:
                errors.append(f"{where}.{key}: must be channel 1..16")
        for value in item.get("values", []) or []:
            _check_pwm(value, f"{where}.values", errors)

    for key, value in (data.get("constants", {}) or {}).items():
        try:
            channel = int(key)
        except (TypeError, ValueError):
            errors.append(f"constants[{key!r}]: key must be a channel number")
            continue
        claim(channel, f"constants[{key}]")
        _check_pwm(value, f"constants[{key}]", errors)

    if "keyboard" in data:
        keyboard = data.get("keyboard") or {}
        if not isinstance(keyboard, dict):
            errors.append("keyboard: must be an object")
        else:
            source = str(keyboard.get("source", "auto")).lower()
            if source not in ("auto", "hid", "keyboard"):
                errors.append("keyboard.source: must be auto, hid, or keyboard")
            for field_name in ("axis_rate", "throttle_rate"):
                value = keyboard.get(field_name, 600)
                if not isinstance(value, (int, float)) or value <= 0:
                    errors.append(f"keyboard.{field_name}: must be > 0")
            keys = keyboard.get("keys", {}) or {}
            if not isinstance(keys, dict):
                errors.append("keyboard.keys: must be an object")
            else:
                used_keys: dict[str, str] = {}
                for action, key_name in keys.items():
                    if action not in DEFAULT_KEYS:
                        errors.append(f"keyboard.keys.{action}: unknown action")
                    try:
                        resolve_keycode(key_name)
                    except ValueError as exc:
                        errors.append(f"keyboard.keys.{action}: {exc}")
                    lowered = str(key_name).lower()
                    if lowered in used_keys and used_keys[lowered] != action:
                        errors.append(
                            f"keyboard.keys.{action}: key {key_name!r} already used by "
                            f"{used_keys[lowered]}"
                        )
                    used_keys[lowered] = action

    return errors


def cmd_config_check() -> int:
    errors = validate_config(HID_CONFIG)
    if errors:
        for item in errors:
            err(item)
        return 4
    print(f"OK: {HID_CONFIG}")
    return 0


def cmd_config_show() -> int:
    print(f"root        {display_path(ROOT)}")
    print(f"sitl        {display_path(find_sitl()) if find_sitl() else 'not found'}")
    print(f"eeprom      {display_path(EEPROM)}")
    print(f"hid config  {display_path(HID_CONFIG)}")
    print(f"backups     {display_path(BACKUPS)}")
    print(f"logs        {display_path(LOGS)}")
    print(f"pid dir     {display_path(RUN)}")
    return 0


def cmd_invert(channel: int, restart: bool = False) -> int:
    data = json.loads(HID_CONFIG.read_text(encoding="utf-8"))
    target = None
    for item in data.get("axes", []):
        if item.get("channel") == channel:
            target = item
            break
    if target is None:
        err(f"CH{channel} is not an axis channel in {display_path(HID_CONFIG)}")
        return 1

    target["reverse"] = not bool(target.get("reverse", False))
    HID_CONFIG.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"CH{channel}: axis {target.get('axis')} reverse="
        f"{str(target['reverse']).lower()}"
    )
    audit(f"invert CH{channel} axis={target.get('axis')} reverse={target['reverse']}")

    errors = validate_config(HID_CONFIG)
    if errors:
        for item in errors:
            err(item)
        return 1

    if restart:
        stop_component("bridge")
        return start_bridge()
    print("next: .\\hidctl.cmd restart bridge")
    return 0


def _cli_commands(path: Path) -> list[str]:
    commands: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            commands.append(stripped)
    return commands


def _cli_session(port: int, commands: list[str], save: bool) -> tuple[list[str], int]:
    """Enter the INAV CLI with '#', send commands, optionally 'save'.

    Returns (error lines, command count).
    """
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.settimeout(0.2)
    output = bytearray()

    def drain() -> None:
        while True:
            try:
                chunk = sock.recv(8192)
            except (socket.timeout, OSError):
                return
            if not chunk:
                return
            output.extend(chunk)

    sock.sendall(b"#")
    time.sleep(0.5)
    drain()

    for command in commands:
        sock.sendall(command.encode() + b"\r\n")
        time.sleep(0.012)
        drain()

    time.sleep(0.3)
    drain()

    if save:
        sock.sendall(b"save\r\n")
        time.sleep(0.5)
        drain()

    try:
        sock.close()
    except OSError:
        pass

    text = output.decode("utf-8", errors="replace")
    errors = [
        line.strip()
        for line in text.splitlines()
        if not line.strip().startswith("#")
        and ("nknown" in line or "nvalid" in line or "rror" in line or "ailed" in line)
    ]
    return errors, len(commands)


def cmd_config_load(file: str | None, port: int, save: bool) -> int:
    path = Path(file).expanduser() if file else CONFIG / "INAV_SITL_MINIMAL_NODEFAULTS.txt"
    if not path.is_file():
        err(f"CLI file not found: {path}")
        return 1
    if not port_open(port):
        err(f"SITL is not listening on 127.0.0.1:{port}; run 'hidctl.cmd start sitl' first")
        return 1

    commands = _cli_commands(path)
    if not commands:
        err(f"no commands in {path}")
        return 1

    audit(f"config load file={path} port={port} save={save} commands={len(commands)}")

    print(f"loading {len(commands)} CLI commands from {display_path(path)} into 127.0.0.1:{port}")
    errors, count = _cli_session(port, commands, save)
    print(f"sent {count} commands" + (" and requested save" if save else " (not saved)"))

    if errors:
        print(f"{len(errors)} error line(s):")
        for line in errors[:20]:
            print(f"  {line}")
    else:
        print("no error lines in the CLI response")

    if save:
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and port_open(port):
            time.sleep(0.2)
        while time.monotonic() < deadline and not port_open(port):
            time.sleep(0.2)
        if port_open(port):
            print("SITL rebooted and is listening again")
            return 0
        err("SITL did not come back after save; check logs\\sitl.log")
        return 1
    return 0


# ---------------------------------------------------------------------------
# HID setup wizard
# ---------------------------------------------------------------------------
SETUP_BASELINE_SECONDS = 0.6
SETUP_STICK_SECONDS = 2.0
SETUP_KNOB_SECONDS = 1.2
SETUP_BUTTON_SECONDS = 0.8
SETUP_WAIT_SECONDS = 8.0
SETUP_HOLD_SECONDS = 0.8
SETUP_MIN_DELTA = 0.35


def _ask(message: str) -> None:
    try:
        input(message)
    except EOFError:
        raise KeyboardInterrupt


def _measure(pad, seconds: float) -> tuple[list[float], list[bool]]:
    """Average axes and any-pressed buttons over a sampling window."""
    sums = [0.0] * pad.num_axes
    pressed = [False] * pad.num_buttons
    count = 0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        axes, buttons = pad.poll()
        for index, value in enumerate(axes):
            sums[index] += value
        for index, value in enumerate(buttons):
            pressed[index] = pressed[index] or bool(value)
        count += 1
        time.sleep(0.02)
    means = [value / max(1, count) for value in sums]
    return means, pressed


def _wait_axis_change(
    pad, base: list[float], timeout: float, threshold: float = 0.5
) -> tuple[int, float] | None:
    """Wait until any axis deviates from base; return (axis, delta)."""
    end = time.monotonic() + timeout
    best_axis, best_abs = 0, 0.0
    next_report = time.monotonic() + 1.0
    while time.monotonic() < end:
        axes, _ = pad.poll()
        deltas = [axes[index] - base[index] for index in range(len(base))]
        axis = max(range(len(deltas)), key=lambda index: abs(deltas[index]))
        if abs(deltas[axis]) > best_abs:
            best_abs = abs(deltas[axis])
            best_axis = axis
        if abs(deltas[axis]) >= threshold:
            print()
            return axis, deltas[axis]
        if time.monotonic() >= next_report:
            print(".", end="", flush=True)
            next_report += 1.0
        time.sleep(0.02)
    print()
    print(f"  largest change: axis {best_axis} {best_abs:+.2f} (need {threshold:+.2f})")
    return None


def _wait_button_change(
    pad, base: list[bool], timeout: float
) -> list[int] | None:
    """Wait until any button changes state; return the changed indexes."""
    end = time.monotonic() + timeout
    next_report = time.monotonic() + 1.0
    while time.monotonic() < end:
        _, buttons = pad.poll()
        changed = [
            index for index in range(len(base)) if bool(buttons[index]) != base[index]
        ]
        if changed:
            print()
            return changed
        if time.monotonic() >= next_report:
            print(".", end="", flush=True)
            next_report += 1.0
        time.sleep(0.02)
    print()
    return None


def _detect_stick(pad, label: str, direction: str) -> tuple[int, float] | None:
    for attempt in range(3):
        _ask(f"\n{label}: center the stick, then press Enter")
        base, _ = _measure(pad, SETUP_BASELINE_SECONDS)
        print(
            f"now move {label} {direction} to maximum and hold it "
            f"(waiting up to {SETUP_WAIT_SECONDS:.0f}s)"
        )
        found = _wait_axis_change(pad, base, SETUP_WAIT_SECONDS)
        if found is None:
            print(f"  no axis moved, attempt {attempt + 1}/3 failed")
            continue
        axis, _ = found
        held, _ = _measure(pad, SETUP_HOLD_SECONDS)
        delta = held[axis] - base[axis]
        if abs(delta) >= SETUP_MIN_DELTA:
            return axis, delta
        print(f"  movement too small (axis {axis}: {delta:+.2f}), attempt {attempt + 1}/3 failed")
    return None


def _detect_knob(pad) -> tuple[int, bool] | None:
    for attempt in range(3):
        _ask("\nMode knob: turn it to the lowest position, then press Enter")
        low, _ = _measure(pad, SETUP_KNOB_SECONDS)
        print(f"now turn the mode knob to the highest position (waiting up to {SETUP_WAIT_SECONDS:.0f}s)")
        found = _wait_axis_change(pad, low, SETUP_WAIT_SECONDS)
        if found is None:
            print(f"  no axis moved, attempt {attempt + 1}/3 failed")
            continue
        axis, _ = found
        high, _ = _measure(pad, SETUP_HOLD_SECONDS)
        delta = high[axis] - low[axis]
        if abs(delta) >= SETUP_MIN_DELTA:
            return axis, delta < 0
        print(f"  movement too small (axis {axis}: {delta:+.2f}), attempt {attempt + 1}/3 failed")
    return None


def _detect_switch(pad, label: str) -> tuple[int, bool] | None:
    for attempt in range(3):
        _ask(f"\n{label}: set the switch LOW, then press Enter")
        _, low = _measure(pad, SETUP_BUTTON_SECONDS)
        print(f"now flip {label} to HIGH (waiting up to {SETUP_WAIT_SECONDS:.0f}s)")
        changed = _wait_button_change(pad, low, SETUP_WAIT_SECONDS)
        if changed is None:
            print(f"  no button changed, attempt {attempt + 1}/3 failed")
            continue
        if len(changed) > 1:
            print(f"  several buttons changed at once {changed}; move one switch only")
            continue
        button = changed[0]
        _, high = _measure(pad, SETUP_HOLD_SECONDS)
        return button, not high[button]
    return None


def cmd_setup(no_write: bool = False, restart: bool = False) -> int:
    try:
        import hid2msp
    except Exception as exc:  # noqa: BLE001
        err(f"cannot import hid2msp: {exc}")
        return 1

    try:
        pad = hid2msp.Gamepad()
    except Exception as exc:  # noqa: BLE001
        err(f"no gamepad: {exc}")
        err("install pygame and connect a HID controller, or use keyboard mode")
        return 1

    print("=== HID channel setup ===")
    print(f"device: {pad.name}  axes={pad.num_axes} buttons={pad.num_buttons}")
    print("For each step: get ready, press Enter, then move the control.")
    print("The wizard waits up to %.0f s for the movement and reports what it sees." % SETUP_WAIT_SECONDS)
    print("Ctrl-C cancels without writing anything.\n")

    sticks = [
        ("CH1 Roll", "roll (aileron)", "right", False),
        ("CH2 Pitch", "pitch", "up (pull)", True),
        ("CH3 Throttle", "throttle", "up to maximum", False),
        ("CH4 Yaw", "yaw (rudder)", "right", False),
    ]

    detected: list[tuple[int, bool]] = []
    try:
        for label, name, direction, invert in sticks:
            result = _detect_stick(pad, f"{label} {name}", direction)
            if result is None:
                err(f"{label}: detection failed, aborting")
                return 1
            axis, delta = result
            # Pulling the pitch stick back ("up") must lower CH2, which is
            # what makes INAV command nose-up.  Hence the extra inversion.
            inverted = (delta < 0) != invert
            detected.append((axis, inverted))
            print(f"  -> axis {axis}, {'reversed' if inverted else 'normal'}")

        knob = _detect_knob(pad)
        if knob is None:
            err("mode knob: detection failed, aborting")
            return 1
        print(f"  -> axis {knob[0]}, {'reversed' if knob[1] else 'normal'}")

        swc = _detect_switch(pad, "SWC (NAV WP)")
        if swc is None:
            err("SWC: detection failed, aborting")
            return 1
        print(f"  -> button {swc[0]}")

        swb = _detect_switch(pad, "SWB (ARM)")
        if swb is None:
            err("SWB: detection failed, aborting")
            return 1
        print(f"  -> button {swb[0]}")
    except KeyboardInterrupt:
        print("\ncancelled, nothing written")
        return 130

    axes = []
    for channel, (label, _name, _direction, _invert), (axis, inverted) in zip(
        range(1, 5), sticks, detected
    ):
        axes.append(
            {
                "axis": axis,
                "channel": channel,
                "kind": "bipolar",
                "trim": 1500,
                "reverse": inverted,
                "deadband": 0.03,
                "expo": 0.0,
            }
        )

    axes.append(
        {
            "axis": knob[0],
            "channel": 8,
            "kind": "multi",
            "levels": 6,
            "values": [1000, 1200, 1400, 1600, 1800, 2000],
            "reverse": knob[1],
        }
    )
    axes.append(
        {
            "axis": knob[0],
            "channel": 5,
            "kind": "tri",
            "threshold": 0.0,
            "reverse": knob[1],
        }
    )

    buttons = []
    for channel, (button, invert), name in ((6, swc, "SWC"), (7, swb, "SWB")):
        buttons.append(
            {
                "button": button,
                "channel": channel,
                "low": 2000 if invert else 1000,
                "high": 1000 if invert else 2000,
                "toggle": False,
            }
        )

    data = json.loads(HID_CONFIG.read_text(encoding="utf-8"))
    data["axes"] = axes
    data["buttons"] = buttons
    data["constants"] = {"9": 2000}
    data["notes"] = f"Calibrated with hidctl setup on Windows: {pad.name}."
    data["channel_map"] = {
        "1": f"Roll (axis{detected[0][0]})",
        "2": f"Pitch (axis{detected[1][0]})",
        "3": f"Throttle (axis{detected[2][0]})",
        "4": f"Yaw (axis{detected[3][0]})",
        "5": f"Knob zone (axis{knob[0]})",
        "6": f"SWC NAV WP (button{swc[0]})",
        "7": f"SWB ARM (button{swb[0]})",
        "8": f"6-position mode (axis{knob[0]})",
        "9": "NAV LAUNCH constant 2000",
    }

    print("\n=== result ===")
    print(f"device: {pad.name}  axes={pad.num_axes} buttons={pad.num_buttons}")
    print(f"{'channel':8} {'axis/button':12} direction")
    for channel, (label, _name, _direction, _invert), (axis, inverted) in zip(
        range(1, 5), sticks, detected
    ):
        print(f"CH{channel:<6} axis {axis:<7} {'reversed' if inverted else 'normal'}")
    print(f"CH8     axis {knob[0]:<7} 6 positions, {'reversed' if knob[1] else 'normal'}")
    print(f"CH5     axis {knob[0]:<7} 3-zone indicator")
    print(f"CH6     button {swc[0]}")
    print(f"CH7     button {swb[0]}")
    print("CH9     constant 2000")

    if no_write:
        print("\n--no-write: config\\hid2msp_inav.json not modified")
        pad.close()
        return 0

    backup = HID_CONFIG.with_suffix(".json.bak")
    try:
        shutil.copyfile(HID_CONFIG, backup)
        HID_CONFIG.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        err(f"cannot write {HID_CONFIG}: {exc}")
        pad.close()
        return 1

    errors = validate_config(HID_CONFIG)
    print(f"\nwrote {display_path(HID_CONFIG)} (backup: {display_path(backup)})")
    if errors:
        for item in errors:
            err(item)
        pad.close()
        return 1

    pad.close()

    if restart:
        print("restarting bridge ...")
        stop_component("bridge")
        rc = start_bridge()
        if rc != 0:
            return rc
    print("next: .\\hidctl.cmd restart bridge   (or rerun with --restart)")
    return 0


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------
def cmd_doctor() -> int:
    checks: list[tuple[str, bool, str]] = []

    sitl = find_sitl()
    checks.append(("SITL binary", sitl is not None, str(sitl) if sitl else "not found"))

    xp = xplane_info()
    checks.append(("X-Plane", xp["path"] is not None, _xplane_label(xp)))
    hitl = hitl_info(xp)
    checks.append(("HITL plugin", hitl["installed"], _hitl_label(hitl)))
    checks.append(("Python", sys.version_info >= (3, 10), sys.version.split()[0]))
    checks.append(("bridge script", BRIDGE.is_file(), str(BRIDGE)))

    keyboard_enabled = True
    keyboard_source = "auto"
    count = 0
    try:
        raw = json.loads(HID_CONFIG.read_text(encoding="utf-8"))
        keyboard_enabled = bool((raw.get("keyboard") or {}).get("enabled", True))
        keyboard_source = str((raw.get("keyboard") or {}).get("source", "auto")).lower()
    except Exception:
        pass

    try:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame  # type: ignore

        pygame.init()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        pygame.quit()
        if count > 0:
            checks.append(("pygame / HID", True, f"{count} joystick(s)"))
        elif keyboard_enabled and keyboard_source in ("auto", "keyboard"):
            checks.append(("pygame / HID", True, "0 joysticks; keyboard fallback"))
        else:
            checks.append(("pygame / HID", False, "0 joysticks and keyboard disabled/forced hid"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("pygame / HID", False, str(exc)))

    keyboard_required = keyboard_enabled and (
        keyboard_source == "keyboard" or (keyboard_source == "auto" and count == 0)
    )
    if keyboard_required:
        checks.append(
            (
                "keyboard input",
                input_available(),
                "GetAsyncKeyState ready" if input_available() else "user32 unavailable",
            )
        )

    errors = validate_config(HID_CONFIG)
    checks.append(("HID config", not errors, f"{len(errors)} error(s)" if errors else "ok"))

    eeprom_ok = (
        EEPROM.is_file() and EEPROM.stat().st_size >= 8192 and EEPROM.stat().st_size % 4096 == 0
    )
    checks.append(
        (
            "eeprom",
            eeprom_ok,
            f"{EEPROM.stat().st_size} bytes" if EEPROM.is_file() else "missing",
        )
    )

    for port in PORTS:
        checks.append((f"port {port}", True, "open" if port_open(port) else "closed (ok if stopped)"))

    failed = False
    for name, ok, detail in checks:
        if not ok:
            failed = True
        print(f"{'PASS' if ok else 'FAIL':4}  {name:14}  {detail}")

    if errors:
        for item in errors:
            print(f"      - {item}")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------
def acquire_lock() -> bool:
    ensure_dirs()
    lock = RUN / "hidctl.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as fh:
            fh.write(f"{os.getpid()}\n{now()}\n")
        return True
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            age = 0
        if age > 120:
            try:
                lock.unlink()
            except OSError:
                pass
            return acquire_lock()
        err("another hidctl operation is in progress (run\\hidctl.lock)")
        return False


def release_lock() -> None:
    try:
        (RUN / "hidctl.lock").unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hidctl",
        description="Manage INAV SITL and the HID-to-MSP bridge on Windows. X-Plane is external.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("start", "stop", "restart"):
        sp = sub.add_parser(name)
        sp.add_argument(
            "component",
            nargs="?",
            default="all",
            choices=("all", "sitl", "bridge"),
            help="component to manage (default: all)",
        )
        sp.add_argument(
            "-v",
            "--verbose",
            dest="verbose",
            action="store_true",
            default=True,
            help="print status/log paths (default)",
        )
        sp.add_argument(
            "-q",
            "--quiet",
            dest="verbose",
            action="store_false",
            help="suppress output",
        )
        if name == "start":
            sp.add_argument(
                "-f",
                "--follow",
                action="store_true",
                help="after starting, follow logs on stdout until Ctrl-C",
            )

    sp = sub.add_parser("status")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("logs")
    sp.add_argument(
        "component",
        nargs="?",
        default="all",
        choices=("all", "sitl", "bridge", "hidctl"),
    )
    sp.add_argument("-f", "--follow", action="store_true")
    sp.add_argument("-n", "--lines", type=int, default=50)

    backup = sub.add_parser("backup")
    backup_sub = backup.add_subparsers(dest="backup_target", required=True)
    bp = backup_sub.add_parser("eeprom")
    bp.add_argument("--name", default=None)

    sub.add_parser("backups")

    restore = sub.add_parser("restore")
    restore_sub = restore.add_subparsers(dest="restore_target", required=True)
    rp = restore_sub.add_parser("eeprom")
    rp.add_argument("file")
    rp.add_argument("--yes", action="store_true")
    rp.add_argument("--no-start", action="store_true")
    rp.add_argument("--no-backup", action="store_true")

    reset = sub.add_parser("reset")
    reset_sub = reset.add_subparsers(dest="reset_target", required=True)
    ep = reset_sub.add_parser("eeprom")
    ep.add_argument("--yes", action="store_true")
    ep.add_argument("--no-backup", action="store_true")

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("check")
    config_sub.add_parser("show")
    config_load = config_sub.add_parser("load")
    config_load.add_argument("--file", default=None, help="CLI file (default config\\INAV_SITL_MINIMAL_NODEFAULTS.txt)")
    config_load.add_argument("--port", type=int, default=5760, help="SITL MSP port (default 5760)")
    config_load.add_argument("--no-save", action="store_true", help="send commands without save/reboot")

    sub.add_parser("doctor")

    setup = sub.add_parser("setup", help="guided HID channel setup (axis, direction, switches)")
    setup.add_argument("--no-write", action="store_true", help="show the result without writing the config")
    setup.add_argument("--restart", action="store_true", help="restart the bridge after writing")

    invert = sub.add_parser("invert", help="toggle reverse for one RC channel")
    invert.add_argument("channel", type=int, help="RC channel number (1-16)")
    invert.add_argument("--restart", action="store_true", help="restart the bridge after writing")

    sub.add_parser("version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command
    audit("run " + " ".join(sys.argv))

    mutating = command in {
        "start",
        "stop",
        "restart",
        "backup",
        "restore",
        "reset",
        "setup",
        "invert",
    } or (command == "config" and getattr(args, "config_command", None) == "load")
    if mutating and not acquire_lock():
        return 1
    try:
        if command == "start":
            return cmd_start(args.component, verbose=args.verbose, follow=args.follow)
        if command == "stop":
            return cmd_stop(args.component, verbose=args.verbose)
        if command == "restart":
            return cmd_restart(args.component, verbose=args.verbose)
        if command == "status":
            return cmd_status(args.json)
        if command == "logs":
            return cmd_logs(args.component, args.follow, args.lines)
        if command == "backup":
            if args.backup_target != "eeprom":
                return 2
            return cmd_backup(args.name)
        if command == "backups":
            return cmd_backups()
        if command == "restore":
            if args.restore_target != "eeprom":
                return 2
            return cmd_restore(args.file, args.yes, args.no_start, args.no_backup)
        if command == "reset":
            if args.reset_target != "eeprom":
                return 2
            return cmd_reset(args.no_backup, args.yes)
        if command == "config":
            if args.config_command == "load":
                return cmd_config_load(args.file, args.port, not args.no_save)
            return cmd_config_check() if args.config_command == "check" else cmd_config_show()
        if command == "doctor":
            return cmd_doctor()
        if command == "setup":
            return cmd_setup(args.no_write, args.restart)
        if command == "invert":
            return cmd_invert(args.channel, args.restart)
        if command == "version":
            print(f"hidctl {VERSION} (windows)")
            return 0
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        err(str(exc))
        return 1
    finally:
        if mutating:
            release_lock()


if __name__ == "__main__":
    _exit_code = main()
    audit(f"exit rc={_exit_code}")
    raise SystemExit(_exit_code)
