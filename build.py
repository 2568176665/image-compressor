from __future__ import annotations

import argparse
import os
import shutil
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

EXCLUDED_SCAN_DIRS = {
    ".git",
    ".venv",
    ".codegraph",
    ".claude",
    "ImageMagick",
}

DIRECTORIES_TO_REMOVE = {
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

FILES_TO_REMOVE = {
    "compression.log",
    "nuitka-crash-report.xml",
    ".imagemagick_update.lock",
}

FILE_SUFFIXES_TO_REMOVE = {
    ".pyc",
    ".pyo",
}

FILE_PATTERNS_TO_REMOVE = {
    "*.spec",
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
    candidates: set[Path] = set()

    for name in DIRECTORIES_TO_REMOVE:
        path = root / name
        if path.exists():
            candidates.add(path)

    for name in FILES_TO_REMOVE:
        path = root / name
        if path.exists():
            candidates.add(path)

    for pattern in FILE_PATTERNS_TO_REMOVE:
        for path in root.glob(pattern):
            candidates.add(path)

    for current_root, dir_names, file_names in os.walk(root, topdown=True):
        dir_names[:] = [name for name in dir_names if name not in EXCLUDED_SCAN_DIRS]
        current = Path(current_root)

        for dir_name in dir_names:
            if dir_name in DIRECTORIES_TO_REMOVE:
                candidates.add(current / dir_name)

        for file_name in file_names:
            file_path = current / file_name
            if file_name in FILES_TO_REMOVE:
                candidates.add(file_path)
            if file_path.suffix.lower() in FILE_SUFFIXES_TO_REMOVE:
                candidates.add(file_path)
            if file_path.suffix.lower() == ".spec":
                candidates.add(file_path)

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

    version = read_project_version()
    version_file = write_version_file(version)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--paths",
        str(SRC_DIR),
        "--version-file",
        str(version_file),
    ]

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
    elif output_path.suffix.lower() != ".exe":
        raise RuntimeError(f"Unexpected build artifact: {output_path}")


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
