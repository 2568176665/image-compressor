from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import features


CODEC_FORMATS = ("jpg", "png", "webp", "avif")
CODEC_EXECUTABLES = {
    "jpg": "cjpegli.exe",
    "png": "pngquant.exe",
    "oxipng": "oxipng.exe",
    "webp": "cwebp.exe",
    "avif": "avifenc.exe",
}
CODEC_VERSION_COMMANDS = {
    "cjpegli.exe": ["-h"],
    "pngquant.exe": ["--version"],
    "oxipng.exe": ["--version"],
    "cwebp.exe": ["-version"],
    "avifenc.exe": ["--version"],
}
METRIC_EXECUTABLE = "ssimulacra2.exe"
VERSION_PATTERN = re.compile(r"\b(?:v)?(\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?)\b")
MANIFEST_FILENAME = "manifest.json"
PACKAGED_CODEC_RELATIVE_DIR = Path("codecs") / "windows-x64"
SOURCE_CODEC_RELATIVE_DIR = Path("src") / "third_party" / "codecs" / "windows-x64"
StatusCallback = Callable[[str], None]


@dataclass(slots=True)
class EnsureResult:
    encoder_paths: dict[str, str]
    versions: dict[str, str]
    source: str
    ready: bool
    message: str
    metric_path: str | None = None
    fatal: bool = False


@dataclass(slots=True)
class RuntimeSummary:
    level: str
    message: str
    can_start: bool


def summarize_runtime_result(result: EnsureResult) -> RuntimeSummary:
    if result.fatal or not result.ready:
        return RuntimeSummary(level="error", message=result.message, can_start=False)
    return RuntimeSummary(level="info", message=result.message, can_start=True)


def get_codec_resource_dir(base_dir: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.extend(
            [
                Path(meipass) / PACKAGED_CODEC_RELATIVE_DIR,
                Path(meipass) / "_internal" / PACKAGED_CODEC_RELATIVE_DIR,
            ]
        )

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                executable_dir / PACKAGED_CODEC_RELATIVE_DIR,
                executable_dir / "_internal" / PACKAGED_CODEC_RELATIVE_DIR,
            ]
        )

    if base_dir:
        base_path = Path(base_dir).resolve()
        candidates.extend(
            [
                base_path / PACKAGED_CODEC_RELATIVE_DIR,
                base_path / "_internal" / PACKAGED_CODEC_RELATIVE_DIR,
                base_path / SOURCE_CODEC_RELATIVE_DIR,
            ]
        )

    project_root = Path(__file__).resolve().parents[2]
    candidates.append(project_root / SOURCE_CODEC_RELATIVE_DIR)

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0] if candidates else project_root / SOURCE_CODEC_RELATIVE_DIR


def validate_codec_resources(resource_dir: str | Path) -> list[Path]:
    root = Path(resource_dir).resolve()
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"编码器资源清单缺失: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"编码器资源清单无效: {manifest_path}") from error

    if not isinstance(manifest, dict):
        raise RuntimeError(f"编码器资源清单无效: {manifest_path}")
    if manifest.get("platform") != "windows-x64":
        raise RuntimeError("编码器资源平台必须为 windows-x64")

    encoders = manifest.get("encoders")
    metrics = manifest.get("metrics")
    files = manifest.get("files")
    if not isinstance(encoders, dict) or not isinstance(files, dict):
        raise RuntimeError("编码器资源清单缺少 encoders 或 files")

    if any(encoders.get(name) != executable for name, executable in CODEC_EXECUTABLES.items()):
        raise RuntimeError("编码器资源映射不符合预期")
    required_names = set(CODEC_EXECUTABLES.values())
    if not required_names.issubset(encoders.values()):
        raise RuntimeError("编码器资源清单未包含全部必需编码器")
    if not required_names.issubset(files):
        raise RuntimeError("编码器资源清单未校验全部必需编码器")
    if metrics is not None:
        if not isinstance(metrics, dict) or metrics.get("ssimulacra2") != METRIC_EXECUTABLE:
            raise RuntimeError("感知评分工具映射不符合预期")
        if METRIC_EXECUTABLE not in files:
            raise RuntimeError("感知评分工具未包含在资源清单中")

    validated: list[Path] = []
    for relative_name, expected_hash in files.items():
        if (
            not isinstance(relative_name, str)
            or not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash) is None
        ):
            raise RuntimeError("编码器资源清单包含无效文件项")
        path = (root / relative_name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise FileNotFoundError(f"编码器资源缺失: {path}")
        actual_hash = _sha256(path)
        if actual_hash.lower() != expected_hash.lower():
            raise RuntimeError(f"编码器资源校验失败: {path.name}")
        validated.append(path)

    return [manifest_path, *validated]


class CodecRuntimeManager:
    def __init__(
        self,
        base_dir: str | None = None,
        resource_dir: str | None = None,
    ) -> None:
        self.base_dir = Path(base_dir or self._get_base_dir())
        self.resource_dir = Path(resource_dir) if resource_dir else None

    def ensure_codecs_ready(
        self,
        status_callback: StatusCallback | None = None,
    ) -> EnsureResult:
        if not self._is_supported_platform():
            return self._failure("当前版本仅支持 Windows x64 编码器")

        resource_dir = self.resource_dir or get_codec_resource_dir(self.base_dir)
        try:
            validate_codec_resources(resource_dir)
            manifest = self._load_manifest(resource_dir)
            encoder_paths = self._resolve_encoder_paths(resource_dir, manifest)
            metric_path = self._resolve_metric_path(resource_dir, manifest)
        except (OSError, RuntimeError, UnicodeError, ValueError) as error:
            return self._failure(str(error))

        if not self._pillow_supports_avif():
            return self._failure("当前 Pillow 未启用 AVIF 支持")

        versions: dict[str, str] = {}
        errors: list[str] = []
        manifest_versions = manifest.get("versions", {})
        if not isinstance(manifest_versions, dict):
            return self._failure("编码器资源清单版本信息无效")
        for name, path in encoder_paths.items():
            version = self._get_version(path)
            if version is None:
                errors.append(Path(path).name)
            else:
                versions[name] = manifest_versions.get(Path(path).name, version)

        if errors:
            return self._failure(f"编码器无法运行: {', '.join(errors)}")

        return EnsureResult(
            encoder_paths=encoder_paths,
            metric_path=metric_path,
            versions=versions,
            source="bundled",
            ready=True,
            message=(
                "编码器已就绪: "
                + ", ".join(f"{name} {version}" for name, version in versions.items())
                + ("；感知评分已启用" if metric_path else "；未找到感知评分工具，将仅限制文件大小")
            ),
            fatal=False,
        )

    def _get_base_dir(self) -> str:
        if getattr(sys, "frozen", False):
            return str(Path(sys.executable).resolve().parent)
        return str(Path(__file__).resolve().parents[2])

    def _is_supported_platform(self) -> bool:
        machine = platform.machine().lower()
        return os.name == "nt" and machine in {"amd64", "x86_64", "x64"}

    def _load_manifest(self, resource_dir: Path) -> dict:
        return json.loads((resource_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))

    def _resolve_encoder_paths(self, resource_dir: Path, manifest: dict) -> dict[str, str]:
        encoders = manifest["encoders"]
        paths = {
            format_name: str((resource_dir / encoders[format_name]).resolve())
            for format_name in CODEC_FORMATS
        }
        paths["oxipng"] = str((resource_dir / encoders["oxipng"]).resolve())
        return paths

    def _resolve_metric_path(self, resource_dir: Path, manifest: dict) -> str | None:
        metrics = manifest.get("metrics")
        if not isinstance(metrics, dict):
            return None
        executable = metrics.get("ssimulacra2")
        if executable != METRIC_EXECUTABLE:
            return None
        path = (resource_dir / executable).resolve()
        return str(path) if path.is_file() else None

    def _pillow_supports_avif(self) -> bool:
        try:
            return bool(features.check("avif"))
        except (AttributeError, ValueError):
            return False

    def _get_version(self, executable: str) -> str | None:
        executable_name = Path(executable).name.lower()
        arguments = CODEC_VERSION_COMMANDS.get(executable_name, ["--version"])
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                [executable, *arguments],
                capture_output=True,
                text=True,
                check=False,
                creationflags=creationflags,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if completed.returncode != 0:
            return None
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        match = VERSION_PATTERN.search(output)
        if match:
            return match.group(1)
        if output.lstrip().startswith("Usage:"):
            return "available"
        return output.strip().splitlines()[0][:120] if output.strip() else "unknown"

    def _failure(self, message: str) -> EnsureResult:
        return EnsureResult(
            encoder_paths={},
            metric_path=None,
            versions={},
            source="none",
            ready=False,
            message=message,
            fatal=True,
        )

    def _emit(self, callback: StatusCallback | None, message: str) -> None:
        if callback:
            callback(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.suffix.lower() == ".txt":
        # 许可证文本需忽略 Windows Git autocrlf 带来的换行差异。
        content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(content)
        return digest.hexdigest()

    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
