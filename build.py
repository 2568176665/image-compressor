from __future__ import annotations

import argparse
import os
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

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from imagec.runtime import validate_codec_resources


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


def clean(root: Path) -> int:
    """删除 git 忽略的构建产物和缓存（保留 .venv 与 .codegraph 工作区）。"""
    result = subprocess.run(
        ["git", "clean", "-Xdf", "-e", ".venv", "-e", ".codegraph"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[clean] git clean 失败: {result.stderr.strip()}")
        return 0
    removed = [line for line in result.stdout.splitlines() if line.startswith("Removing ")]
    for line in removed:
        print(f"[clean] {line}")
    print(f"[clean] Done. Removed {len(removed)} path(s).")
    return len(removed)


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
    cmd.extend(build_codec_arguments(codec_resources))

    if onedir:
        cmd.append("--onedir")
    else:
        cmd.append("--onefile")

    if ICON_FILE.exists():
        cmd.extend(["--icon", str(ICON_FILE)])
    else:
        print(f"[build] Icon not found, skip: {ICON_FILE}")

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


def validate_build_output(output_path: Path, onedir: bool) -> None:
    if not output_path.exists():
        raise FileNotFoundError(f"Build output missing: {output_path}")
    if onedir:
        executable = output_path / f"{APP_NAME}.exe"
        if not executable.exists():
            raise FileNotFoundError(f"Onedir executable missing: {executable}")
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
        payload = output_path.read_bytes()
        required_names = tuple(path.name for path in validate_codec_resources(CODEC_RESOURCE_DIR))
        missing = [name for name in required_names if name.encode("utf-8") not in payload]
        if missing:
            raise RuntimeError(f"Onefile 编码器资源未内置: {', '.join(missing)}")


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
