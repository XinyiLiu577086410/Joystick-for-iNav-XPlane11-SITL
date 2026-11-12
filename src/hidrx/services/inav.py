"""INAV version selection and per-version runtime state."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ..models import EepromMeta, InavInstall, InavSelection
from ..platform.base import InavLocator


class InavError(RuntimeError):
    pass


def _version_key(version: str) -> tuple:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


@dataclass
class InavService:
    locator: InavLocator
    config_dir: Path
    runtime_dir: Path
    active_file: Optional[Path] = None
    env: Optional[Dict[str, str]] = None
    platform_id: str = ""

    def __post_init__(self) -> None:
        self.config_dir = Path(self.config_dir)
        self.runtime_dir = Path(self.runtime_dir)
        if self.active_file is None:
            self.active_file = self.runtime_dir / "inav.json"
        else:
            self.active_file = Path(self.active_file)

    # -- discovery ---------------------------------------------------------
    def list(self) -> List[InavInstall]:
        return sorted(self.locator.discover(), key=lambda item: _version_key(item.version))

    def _find_version(self, version: str) -> InavInstall:
        installs = self.list()
        exact = [item for item in installs if item.version == version]
        if exact:
            return exact[-1]
        prefixed = [item for item in installs if item.version.startswith(version + ".")]
        if prefixed:
            return prefixed[-1]
        raise InavError(f"INAV {version} is not installed (found: {', '.join(i.version for i in installs) or 'none'})")

    # -- active selection --------------------------------------------------
    def read_active(self) -> Optional[dict]:
        if self.active_file is None or not self.active_file.is_file():
            return None
        try:
            data = json.loads(self.active_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def use(self, install: InavInstall) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        payload = {"version": install.version, "path": str(install.path), "platform": self.platform_id}
        self.active_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # -- resolution --------------------------------------------------------
    def resolve(self, version: Optional[str] = None, path: Optional[Path] = None) -> InavSelection:
        env = self.env if self.env is not None else os.environ
        install: Optional[InavInstall] = None
        source = ""

        if path is not None:
            install = self.locator.resolve_path(Path(path))
            source = "cli-path"
            if install is None:
                raise InavError(f"no inav_SITL found at {path}")
        elif version:
            install = self._find_version(version)
            source = "cli-version"
        elif env.get("HIDRX_INAV_PATH"):
            install = self.locator.resolve_path(Path(env["HIDRX_INAV_PATH"]))
            source = "env-path"
            if install is None:
                raise InavError(f"HIDRX_INAV_PATH does not contain inav_SITL: {env['HIDRX_INAV_PATH']}")
        elif env.get("HIDRX_INAV_VERSION"):
            install = self._find_version(env["HIDRX_INAV_VERSION"])
            source = "env-version"
        else:
            active = self.read_active()
            if active and active.get("version"):
                install = self._find_version(str(active["version"]))
                source = "active"
            else:
                installs = self.list()
                if not installs:
                    raise InavError("no INAV SITL installation found; pass --inav-path")
                install = installs[-1]
                source = "auto"

        if install.platform and self.platform_id and install.platform != self.platform_id:
            raise InavError(
                f"INAV SITL at {install.path} is for {install.platform}, current platform is {self.platform_id}"
            )

        runtime = self.runtime_dir / install.version
        eeprom = runtime / "plane.bin"
        cli_config = self.config_dir / "inav" / install.version / "minimal.txt"
        meta = self.read_meta(install.version)
        if meta is not None and meta.version != install.version:
            raise InavError(
                f"eeprom in {runtime} was created for INAV {meta.version}, current is {install.version}"
            )
        return InavSelection(
            install=install,
            eeprom=eeprom,
            cli_config=cli_config if cli_config.is_file() else None,
            source=source,
        )

    # -- eeprom ------------------------------------------------------------
    def meta_path(self, version: str) -> Path:
        return self.runtime_dir / version / "meta.json"

    def read_meta(self, version: str) -> Optional[EepromMeta]:
        path = self.meta_path(version)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return EepromMeta(
            version=str(data.get("inav_version", "")),
            build=str(data.get("build", "")),
            platform=str(data.get("platform", "")),
            sha256=str(data.get("sha256", "")),
        )

    def write_meta(self, selection: InavSelection) -> None:
        runtime = selection.eeprom.parent
        runtime.mkdir(parents=True, exist_ok=True)
        sha = ""
        if selection.eeprom.is_file():
            digest = hashlib.sha256(selection.eeprom.read_bytes()).hexdigest()
            sha = digest
        meta = EepromMeta(
            version=selection.install.version,
            build=selection.install.build,
            platform=self.platform_id,
            sha256=sha,
        )
        (runtime / "meta.json").write_text(
            json.dumps(
                {
                    "inav_version": meta.version,
                    "build": meta.build,
                    "platform": meta.platform,
                    "sha256": meta.sha256,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def ensure_eeprom(self, selection: InavSelection) -> None:
        if not selection.eeprom.is_file():
            raise InavError(
                f"no eeprom for INAV {selection.install.version}: {selection.eeprom}\n"
                f"run: hidctl config load --inav-version {selection.install.version}"
            )
