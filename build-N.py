from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from build import (
    APP_NAME,
    CODEC_PACKAGE_DIR,
    CODEC_RESOURCE_DIR,
    ENTRY_SCRIPT,
    ICON_FILE,
    PROJECT_ROOT,
    SRC_DIR,
    collect_garbage_paths,
    parse_version_parts,
    read_project_version,
    remove_path,
)
from imagec.runtime import validate_codec_resources

OUTPUT_DIR = PROJECT_ROOT / "nuitka-dist"


def dist_folder_name(onefile: bool) -> str:
    return f"{APP_NAME}-onefile" if onefile else APP_NAME


def standalone_dir() -> Path:
    return OUTPUT_DIR / f"{dist_folder_name(onefile=False)}.dist"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean build artifacts and build a Windows exe with Nuitka.",
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
        help="Build in onefile mode. Default is standalone mode.",
    )
    return parser.parse_args()


def find_tcl_library_dir() -> Path | None:
    """定位 Python 安装自带的 Tcl 脚本目录。

    Python 3.14 的 Windows 发行版把 Tcl 9 数据以 zipfs 形式嵌入 tcl90.dll，
    磁盘上并没有 init.tcl；这种情况下启用 tk-inter 插件会直接报错。
    """
    for prefix in {Path(sys.base_prefix), Path(sys.prefix)}:
        tcl_root = prefix / "tcl"
        if not tcl_root.is_dir():
            continue
        for candidate in sorted(tcl_root.glob("tcl*")):
            if (candidate / "init.tcl").is_file():
                return candidate
    return None


def build_command(version: str, onefile: bool) -> list[str]:
    numeric_version = ".".join(str(part) for part in (*parse_version_parts(version), 0))
    # Nuitka 的选项解析器只接受 `--option=value` 形式。
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=onefile" if onefile else "--mode=standalone",
        "--windows-console-mode=disable",
        f"--output-dir={OUTPUT_DIR}",
        f"--output-filename={APP_NAME}.exe",
        # 输出目录名同时也是 Nuitka 的 dist 目录名，两种模式必须错开，
        # 否则先构建的 .dist 会被后一次构建删除。
        f"--output-folder-name={dist_folder_name(onefile)}",
        # 编码器是 exe 与 dll，Nuitka 的 --include-data-dir 会跳过这两类后缀，
        # 因此必须使用 --include-raw-dir 原样复制。
        f"--include-raw-dir={CODEC_RESOURCE_DIR}={CODEC_PACKAGE_DIR.as_posix()}",
        "--company-name=ImageC",
        "--product-name=ImageC",
        "--file-description=ImageC image compressor",
        f"--file-version={numeric_version}",
        f"--product-version={numeric_version}",
        "--assume-yes-for-downloads",
        "--remove-output",
    ]

    tcl_library_dir = find_tcl_library_dir()
    if tcl_library_dir is None:
        print("[build] 未找到 Tcl 脚本目录，跳过 tk-inter 插件（Tcl 数据已内嵌在 DLL 中）")
    else:
        command.append("--enable-plugin=tk-inter")
        command.append(f"--tcl-library-dir={tcl_library_dir}")

    if ICON_FILE.exists():
        command.append(f"--windows-icon-from-ico={ICON_FILE}")
    else:
        print(f"[build] Icon not found, skip: {ICON_FILE}")

    command.append(str(ENTRY_SCRIPT))
    return command


def build(onefile: bool) -> Path:
    if not ENTRY_SCRIPT.exists():
        raise FileNotFoundError(f"Entry script not found: {ENTRY_SCRIPT}")
    if not SRC_DIR.exists():
        raise FileNotFoundError(f"Source directory not found: {SRC_DIR}")

    validate_codec_resources(CODEC_RESOURCE_DIR)

    version = read_project_version()
    command = build_command(version, onefile)

    print(f"[build] Version: {version}")
    print("[build] Running:")
    print("        " + " ".join(command))

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(SRC_DIR), env.get("PYTHONPATH")) if part
    )
    subprocess.run(command, cwd=PROJECT_ROOT, check=True, env=env)

    output_path = validate_build_output(onefile)
    print(f"[build] Build success: {output_path}")
    return output_path


def validate_build_output(onefile: bool) -> Path:
    if onefile:
        output_path = OUTPUT_DIR / f"{APP_NAME}.exe"
        if not output_path.is_file():
            raise FileNotFoundError(f"Build output missing: {output_path}")
        # onefile 载荷经过压缩，无法像 PyInstaller 那样逐字节确认内置资源。
        return output_path

    executable = standalone_dir() / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Standalone executable missing: {executable}")

    resource_dir = standalone_dir() / CODEC_PACKAGE_DIR
    if not (resource_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"编码器资源目录缺失: {resource_dir}")
    validate_codec_resources(resource_dir)
    return standalone_dir()


def clean_workspace(root: Path) -> None:
    """清理垃圾文件，但保留 build.py 的 dist/ 产物。"""
    pyinstaller_dist = root / "dist"
    removed = 0
    for path in collect_garbage_paths(root):
        if path == pyinstaller_dist:
            continue
        if remove_path(path):
            removed += 1
            print(f"[clean] Removed: {path.relative_to(root)}")
    print(f"[clean] Done. Removed {removed} path(s).")


def main() -> int:
    args = parse_args()

    if not args.skip_clean:
        clean_workspace(PROJECT_ROOT)

    if args.clean_only:
        return 0

    build(onefile=args.onefile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
