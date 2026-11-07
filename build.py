from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
ENTRY_SCRIPT = PROJECT_ROOT / "main.py"
SRC_DIR = PROJECT_ROOT / "src"
APP_NAME = "image_compressor"
ICON_FILE = PROJECT_ROOT / "assets" / "app.ico"
CODEC_RESOURCE_DIR = PROJECT_ROOT / "src" / "third_party" / "codecs" / "windows-x64"
CODEC_PACKAGE_DIR = Path("codecs") / "windows-x64"

# 本工具是纯本地桌面程序：不联网、不读写数据库、不解析 XML。
# 砍掉这些模块可以把 PyInstaller 顺带收集的 libcrypto-3-x64.dll(7.8MB)
# 与 libssl-3-x64.dll(1.5MB) 一起丢掉。hashlib 在缺少 _hashlib 时会自动
# 回退到内建的 _sha256/_sha512，编码器清单校验照常工作。
EXCLUDED_MODULES = (
    "_ssl",
    "ssl",
    "_hashlib",
    "http",
    "urllib",
    "email",
    "xml",
    "xmlrpc",
    "sqlite3",
    "asyncio",
    "unittest",
    "pydoc",
    "turtle",
    "tkinter.test",
)

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from imagec.runtime import validate_codec_resources

EXCLUDED_SCAN_DIRS = {
    ".git",
    ".venv",
    ".codegraph",
    ".claude",
    "third_party",
}

DIRECTORIES_TO_REMOVE = {
    "build",
    "dist",
    "nuitka-dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

# 历史 Nuitka 产物，仅用于清理旧工作副本，当前只维护 PyInstaller 一条构建链。
FILES_TO_REMOVE = {
    "compression.log",
    "nuitka-crash-report.xml",
}

FILE_SUFFIXES_TO_REMOVE = {
    ".pyc",
    ".pyo",
    ".spec",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean build artifacts and build a Windows exe with PyInstaller.",
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Only clean junk files and skip building.",
    )
    parser.add_argument(
        "--skip-clean",
        action="store_true",
        help="Skip cleanup before build.",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build in one-file mode. Default is one-dir mode.",
    )
    return parser.parse_args()


def collect_garbage_paths(root: Path) -> list[Path]:
    candidates: list[Path] = []

    for current_root, dir_names, file_names in os.walk(root, topdown=True):
        dir_names[:] = [name for name in dir_names if name not in EXCLUDED_SCAN_DIRS]
        current = Path(current_root)

        for dir_name in tuple(dir_names):
            if dir_name in DIRECTORIES_TO_REMOVE:
                candidates.append(current / dir_name)
                dir_names.remove(dir_name)

        for file_name in file_names:
            file_path = current / file_name
            if file_name in FILES_TO_REMOVE or file_path.suffix.lower() in FILE_SUFFIXES_TO_REMOVE:
                candidates.append(file_path)

    return sorted(candidates)


def remove_path(path: Path) -> bool:
    if not path.exists():
        return False

    try:
        if path.is_dir():
            for attempt in range(2):
                try:
                    shutil.rmtree(path)
                    break
                except OSError:
                    if attempt == 1:
                        raise
                    time.sleep(0.1)
        else:
            path.unlink()
    except OSError as error:
        print(f"[clean] Skip (busy or inaccessible): {path} ({error})")
        return False

    return True


def clean(root: Path) -> int:
    garbage_paths = collect_garbage_paths(root)
    removed_count = 0

    if not garbage_paths:
        print("[clean] No junk files found.")
        return removed_count

    for path in garbage_paths:
        if remove_path(path):
            removed_count += 1
            print(f"[clean] Removed: {path.relative_to(root)}")

    print(f"[clean] Done. Removed {removed_count} path(s).")
    return removed_count


def build(root: Path, onedir: bool) -> None:
    if not ENTRY_SCRIPT.exists():
        raise FileNotFoundError(f"Entry script not found: {ENTRY_SCRIPT}")
    if not SRC_DIR.exists():
        raise FileNotFoundError(f"Source directory not found: {SRC_DIR}")

    codec_resources = validate_codec_resources(CODEC_RESOURCE_DIR)

    version = read_project_version()
    version_file = write_version_file(version)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--noupx",
        "--name",
        APP_NAME,
        "--paths",
        str(SRC_DIR),
        "--version-file",
        str(version_file),
    ]
    # onefile 模式下编码器不打进 exe：PyInstaller 每次启动都会把内置资源
    # 解压到临时目录，20MB 编码器会让每次冷启动都多付一次磁盘写入。
    # 改为构建后放到 exe 同级目录，运行时由 get_codec_resource_dir 找到。
    if onedir:
        cmd.extend(build_codec_arguments(codec_resources))
    cmd.extend(build_exclude_arguments())
    cmd.extend(build_dnd_arguments())

    if onedir:
        cmd.append("--onedir")
    else:
        cmd.append("--onefile")

    if not ICON_FILE.is_file():
        raise FileNotFoundError(f"Icon file missing, refusing to build without an icon: {ICON_FILE}")
    cmd.extend(["--icon", str(ICON_FILE)])

    cmd.append(str(ENTRY_SCRIPT))

    print(f"[build] Version: {version}")
    print("[build] Running:")
    print("        " + " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=root, check=True)
    except subprocess.CalledProcessError:
        print("[build] Build failed. Cleaning non-dist artifacts...")
        print(f"[build] Diagnostics: entry={ENTRY_SCRIPT}, src={SRC_DIR}, icon_exists={ICON_FILE.exists()}")
        _clean_build_artifacts(root, onedir)
        raise
    finally:
        remove_path(version_file)

    _clean_build_artifacts(root, onedir)

    if onedir:
        output_path = root / "dist" / APP_NAME
    else:
        output_path = root / "dist" / f"{APP_NAME}.exe"
        codec_dir = stage_portable_codecs(output_path.parent)
        print(f"[build] 编码器已外置: {codec_dir}")

    validate_build_output(output_path, onedir)
    print(f"[build] Build success: {output_path}")


def _clean_build_artifacts(root: Path, onedir: bool) -> None:
    for name in ("build", "__pycache__"):
        path = root / name
        if path.exists():
            remove_path(path)
            print(f"[build] Removed: {name}")

    for spec in root.glob("*.spec"):
        remove_path(spec)
        print(f"[build] Removed: {spec.name}")

    dist_dir = root / "dist"
    if not onedir and dist_dir.exists():
        for item in dist_dir.iterdir():
            if item.is_dir():
                remove_path(item)
                print(f"[build] Removed: dist/{item.name}")


def read_project_version() -> str:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file_obj:
        data = tomllib.load(file_obj)
    return data["project"]["version"]


def write_version_file(version: str) -> Path:
    major, minor, patch = parse_version_parts(version)
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'ImageC'),
          StringStruct('FileDescription', 'ImageC image compressor'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', '{APP_NAME}'),
          StringStruct('OriginalFilename', '{APP_NAME}.exe'),
          StringStruct('ProductName', 'ImageC'),
          StringStruct('ProductVersion', '{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)"""
    target = Path(tempfile.gettempdir()) / f"{APP_NAME}-version-info.txt"
    target.write_text(content, encoding="utf-8")
    return target


def parse_version_parts(version: str) -> tuple[int, int, int]:
    parts = [int(part) for part in version.split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def read_icon_image_blobs(icon_path: Path = ICON_FILE) -> list[bytes]:
    """解析 ICO 目录，返回每个尺寸的图像数据块，用于校验图标是否真的写进 exe。"""
    data = icon_path.read_bytes()
    if len(data) < 6:
        raise RuntimeError(f"图标文件损坏: {icon_path}")
    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or icon_type != 1 or count == 0:
        raise RuntimeError(f"图标文件格式错误: {icon_path}")
    blobs: list[bytes] = []
    for index in range(count):
        entry_offset = 6 + index * 16
        *_, size, offset = struct.unpack_from("<BBBBHHII", data, entry_offset)
        blob = data[offset : offset + size]
        if not blob or len(blob) != size:
            raise RuntimeError(f"图标数据块损坏: {icon_path} #{index}")
        blobs.append(blob)
    return blobs


def validate_embedded_icon(executable: Path, icon_path: Path = ICON_FILE) -> None:
    """确认 exe 内真正写入了 ICO 的每个图像块，避免 --icon 静默失效。"""
    blobs = read_icon_image_blobs(icon_path)
    payload = executable.read_bytes()
    missing = [index for index, blob in enumerate(blobs) if blob not in payload]
    if missing:
        raise RuntimeError(
            f"可执行文件未内嵌图标资源: {executable}（缺失 {len(missing)}/{len(blobs)} 个尺寸）"
        )


def stage_portable_codecs(dist_dir: Path) -> Path:
    """把编码器整目录复制到 onefile exe 同级，替代打进 exe 内置资源。"""
    target = dist_dir / CODEC_PACKAGE_DIR
    if target.exists():
        remove_path(target)
    shutil.copytree(CODEC_RESOURCE_DIR, target)
    return target


def build_exclude_arguments() -> list[str]:
    arguments: list[str] = []
    for module in EXCLUDED_MODULES:
        arguments.extend(["--exclude-module", module])
    return arguments


def validate_build_output(output_path: Path, onedir: bool) -> None:
    if not output_path.exists():
        raise FileNotFoundError(f"Build output missing: {output_path}")
    if onedir:
        executable = output_path / f"{APP_NAME}.exe"
        if not executable.exists():
            raise FileNotFoundError(f"Onedir executable missing: {executable}")
        validate_embedded_icon(executable)
        resource_candidates = [
            output_path / CODEC_PACKAGE_DIR,
            output_path / "_internal" / CODEC_PACKAGE_DIR,
        ]
        resource_dir = next(
            (candidate for candidate in resource_candidates if (candidate / "manifest.json").is_file()),
            None,
        )
        if resource_dir is None:
            raise FileNotFoundError("Onedir 编码器资源目录缺失")
        validate_codec_resources(resource_dir)
    elif output_path.suffix.lower() != ".exe":
        raise RuntimeError(f"Unexpected build artifact: {output_path}")
    else:
        validate_embedded_icon(output_path)
        codec_dir = output_path.parent / CODEC_PACKAGE_DIR
        if not (codec_dir / "manifest.json").is_file():
            raise FileNotFoundError(f"Onefile 外置编码器目录缺失: {codec_dir}（需与 exe 一同分发）")
        resources = validate_codec_resources(codec_dir)
        payload = output_path.read_bytes()
        # 只查子进程入口的 exe 名字：编码器目录里的 zlib1.dll 之类和 Pillow、
        # tkinter 自带的同名 DLL 无法区分，命名重合不代表编码器被打进了包。
        embedded = [
            path.name
            for path in resources
            if path.suffix.lower() == ".exe" and path.name.encode("utf-8") in payload
        ]
        if embedded:
            raise RuntimeError(f"Onefile 仍内置了编码器: {', '.join(embedded)}")


def build_dnd_arguments() -> list[str]:
    """tkinterdnd2 携带 tkdnd 二进制资源，缺失时不需要额外参数。"""
    if importlib.util.find_spec("tkinterdnd2") is None:
        print("[build] tkinterdnd2 not installed, skip drag-and-drop resources")
        return []
    return ["--collect-data", "tkinterdnd2", "--hidden-import", "tkinterdnd2"]


def build_codec_arguments(resource_files: list[Path]) -> list[str]:
    arguments: list[str] = []
    for resource_file in resource_files:
        relative_path = resource_file.relative_to(CODEC_RESOURCE_DIR)
        destination = CODEC_PACKAGE_DIR / relative_path.parent
        arguments.extend(["--add-data", f"{resource_file}{os.pathsep}{destination.as_posix()}"])
    return arguments


def main() -> int:
    args = parse_args()

    if not args.skip_clean:
        clean(PROJECT_ROOT)

    if args.clean_only:
        return 0

    build(PROJECT_ROOT, onedir=not args.onefile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
