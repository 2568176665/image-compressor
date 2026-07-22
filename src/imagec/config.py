from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "ImageC"
CONFIG_FILENAME = "config.json"
LOG_FILENAME = "compression.log"
DEFAULT_CONFIG = {
    "input_path": os.path.join(".", "input"),
    "auto_output": True,
    "output_path": "",
    "target_size_kb": "100",
    "resize": "不使用",
    "resize_width": "",
    "resize_height": "",
    "format": "jpg",
    "visual_quality": "优质 (85)",
    "max_workers": "4",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


@dataclass(slots=True)
class AppPaths:
    program_dir: Path
    fallback_dir: Path
    active_dir: Path
    config_path: Path
    log_path: Path
    legacy_config_path: Path | None


def get_program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_fallback_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data)
    return Path.home() / "AppData" / "Local"


def is_directory_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, delete=True):
            return True
    except OSError:
        return False


def resolve_app_paths(
    program_dir: Path | None = None,
    fallback_root: Path | None = None,
) -> AppPaths:
    program_dir = Path(program_dir or get_program_dir()).resolve()
    fallback_root = Path(fallback_root or get_fallback_root()).resolve()
    fallback_dir = fallback_root / APP_NAME
    legacy_config_path = program_dir / CONFIG_FILENAME

    if is_directory_writable(program_dir):
        active_dir = program_dir
    else:
        active_dir = fallback_dir

    return AppPaths(
        program_dir=program_dir,
        fallback_dir=fallback_dir,
        active_dir=active_dir,
        config_path=active_dir / CONFIG_FILENAME,
        log_path=active_dir / LOG_FILENAME,
        legacy_config_path=legacy_config_path if legacy_config_path.exists() else None,
    )


class ConfigStore:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.legacy_config_path = paths.legacy_config_path

    def load(self) -> dict:
        config = DEFAULT_CONFIG.copy()
        for candidate in self._load_candidates():
            if not candidate.exists():
                continue
            try:
                with candidate.open("r", encoding="utf-8") as file_obj:
                    loaded = json.load(file_obj)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(loaded, dict):
                config.update(loaded)
            break
        return config

    def save(self, config: dict) -> Path:
        target = self.paths.config_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = DEFAULT_CONFIG.copy()
        payload.update(config)
        with target.open("w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)
        return target

    def _load_candidates(self) -> list[Path]:
        candidates = [self.paths.config_path]
        if self.paths.legacy_config_path and self.paths.legacy_config_path not in candidates:
            candidates.append(self.paths.legacy_config_path)
        return candidates


def configure_logging(paths: AppPaths) -> None:
    paths.log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(paths.log_path, encoding="utf-8")],
        force=True,
    )


def derive_output_path(input_path: str) -> str:
    normalized_path = input_path.strip()
    if not normalized_path:
        return os.path.join(".", "output")

    expanded_path = os.path.expanduser(normalized_path)
    expanded = Path(expanded_path)

    if expanded.is_file():
        base_dir = expanded.parent
    elif expanded.is_dir():
        base_dir = expanded
    elif expanded.suffix.lower() in IMAGE_SUFFIXES:
        base_dir = expanded.parent if str(expanded.parent) else Path(".")
    else:
        base_dir = expanded

    return str(base_dir / "output")
