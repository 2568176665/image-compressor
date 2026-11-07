from __future__ import annotations

import copy
import json
import logging
import logging.handlers
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "ImageC"
CONFIG_FILENAME = "config.json"
LOG_FILENAME = "compression.log"
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUP_COUNT = 3
# 输出方式：决定每张图片的输出目录，以及是否需要追加防覆盖后缀。
OUTPUT_MODE_SIBLING = "sibling"
OUTPUT_MODE_COMPRESSED = "sibling_compressed"
OUTPUT_MODE_CUSTOM = "custom"
OUTPUT_MODE_LABELS: dict[str, str] = {
    OUTPUT_MODE_SIBLING: "原图同目录",
    OUTPUT_MODE_COMPRESSED: "原图同目录\\compressed",
    OUTPUT_MODE_CUSTOM: "自定义目录…",
}
OUTPUT_MODE_KEYS: dict[str, str] = {
    label: mode for mode, label in OUTPUT_MODE_LABELS.items()
}
OUTPUT_SUBDIR_NAME = "compressed"
# 自动输出（同目录/同目录子目录）时统一加后缀，避免与源图重名，也便于把产物和原图区分开。
AUTO_OUTPUT_NAME_SUFFIX = "_ic"

DEFAULT_CONFIG: dict[str, object] = {
    "input_paths": [],
    "output_mode": OUTPUT_MODE_COMPRESSED,
    "custom_output_dir": "",
    "target_size_kb": "100",
    "resize": "不使用",
    "format": "jpg",
    "max_workers": "4",
    "overwrite": False,
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


@dataclass(slots=True)
class AppPaths:
    program_dir: Path
    active_dir: Path
    config_path: Path
    log_path: Path
    legacy_config_path: Path | None


def get_program_dir() -> Path:
    # PyInstaller 冻结环境：sys.executable 指向用户实际放置的 exe。
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
        config = copy.deepcopy(DEFAULT_CONFIG)
        for candidate in self._load_candidates():
            if not candidate.exists():
                continue
            try:
                with candidate.open("r", encoding="utf-8") as file_obj:
                    loaded = json.load(file_obj)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(loaded, dict):
                config.update({key: value for key, value in loaded.items() if key in DEFAULT_CONFIG})
            break
        config["input_paths"] = coerce_input_paths(config.get("input_paths"))
        return config

    def save(self, config: dict) -> Path:
        target = self.paths.config_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = copy.deepcopy(DEFAULT_CONFIG)
        payload.update(config)
        payload["input_paths"] = coerce_input_paths(payload.get("input_paths"))
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
        handlers=[
            logging.handlers.RotatingFileHandler(
                paths.log_path,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        ],
        force=True,
    )


def coerce_input_paths(value: object) -> list[str]:
    """把配置里的输入列表清洗成非空字符串列表，兼容旧版字符串写法。"""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        return []
    paths: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            paths.append(text)
    return paths


def normalize_output_mode(value: object) -> str:
    mode = str(value or "").strip()
    return mode if mode in OUTPUT_MODE_LABELS else OUTPUT_MODE_COMPRESSED


def output_name_suffix(mode: str) -> str:
    """自动输出方式下给输出文件名追加的后缀；自定义目录保持原有命名。"""
    return "" if normalize_output_mode(mode) == OUTPUT_MODE_CUSTOM else AUTO_OUTPUT_NAME_SUFFIX


def resolve_output_dir(mode: str, input_file: str, custom_dir: str = "") -> str:
    """按输出方式解析单张图片的输出目录。"""
    normalized_mode = normalize_output_mode(mode)

    if normalized_mode == OUTPUT_MODE_CUSTOM:
        target = os.path.expanduser(custom_dir.strip())
        if not target:
            raise ValueError("自定义输出目录未设置")
        return str(Path(target))

    source = os.path.expanduser(input_file.strip())
    base_dir = Path(source).parent if source else Path(".")

    if normalized_mode == OUTPUT_MODE_SIBLING:
        return str(base_dir)
    return str(base_dir / OUTPUT_SUBDIR_NAME)
