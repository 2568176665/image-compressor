import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    import py7zr
except ImportError:  # pragma: no cover - optional runtime dependency
    py7zr = None


ARCHIVE_INDEX_URL = "https://imagemagick.org/archive/binaries/"
VERSION_PATTERN = re.compile(r"ImageMagick (\d+\.\d+\.\d+-\d+)")
PACKAGE_PATTERN = re.compile(
    r'href="(ImageMagick-(7\.\d+\.\d+-\d+)-portable-Q16(?:-HDRI)?-(arm64|x64|x86)\.7z)"',
    re.IGNORECASE,
)


StatusCallback = Callable[[str], None]


@dataclass(slots=True)
class EnsureResult:
    magick_path: str | None
    version: str | None
    source: str
    updated: bool
    ready: bool
    message: str
    fatal: bool = False


class ImageMagickManager:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or self._get_base_dir())
        self.lock_file = self.base_dir / ".imagemagick_update.lock"
        self.install_dir = self.base_dir / "ImageMagick"
        self.staging_dir = self.base_dir / "ImageMagick.staging"
        self.backup_dir = self.base_dir / "ImageMagick.backup"

    def _get_base_dir(self) -> str:
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def get_magick_path(self) -> str | None:
        runtime = self._get_available_runtime()
        if runtime:
            return runtime["path"]
        return None

    def get_local_install(self) -> dict | None:
        return self._resolve_install(self.install_dir, "private")

    def ensure_imagemagick_ready(
        self,
        status_callback: StatusCallback | None = None,
    ) -> EnsureResult:
        try:
            self._repair_install_dirs()
        except Exception as error:
            return self._failure_result(
                f"修复本地 ImageMagick 目录失败: {error}",
            )

        local = self.get_local_install()
        if local is None:
            self._emit(status_callback, "未检测到本地 ImageMagick，准备下载...")
        else:
            self._emit(
                status_callback,
                f"检测到 ImageMagick {local['version'] or '未知版本'}，检查更新中...",
            )

        try:
            lock_acquired = self._acquire_lock(local_available=local is not None)
        except Exception as error:
            return self._failure_result(
                f"创建 ImageMagick 更新锁失败: {error}",
            )

        if not lock_acquired:
            return self._result_from_runtime(
                self._get_available_runtime(),
                updated=False,
                message="另一个实例正在更新 ImageMagick，当前继续使用现有版本。",
            )

        try:
            return self._ensure_imagemagick_ready_locked(local, status_callback)
        except Exception as error:  # pragma: no cover - defensive fallback
            return self._failure_result(f"更新 ImageMagick 失败: {error}")
        finally:
            self._release_lock()

    def _ensure_imagemagick_ready_locked(
        self,
        local: dict | None,
        status_callback: StatusCallback | None,
    ) -> EnsureResult:
        try:
            remote = self._fetch_latest_package()
        except Exception as error:
            return self._failure_result(f"检查更新失败: {error}")

        local_version = (local or {}).get("version")
        if local and local_version and self._compare_versions(local_version, remote["version"]) >= 0:
            return EnsureResult(
                magick_path=local["path"],
                version=local_version,
                source=local["source"],
                updated=False,
                ready=True,
                message=f"ImageMagick 已是最新版本 {local_version}",
                fatal=False,
            )

        if local and not local_version:
            self._emit(status_callback, "本地版本未知，准备拉取最新版本...")
        elif local_version:
            self._emit(
                status_callback,
                f"发现新版本 {remote['version']}，当前版本 {local_version}，开始下载...",
            )
        else:
            self._emit(status_callback, f"开始下载 ImageMagick {remote['version']} ...")

        archive_path = None
        try:
            archive_path, _digest = self._download_package(
                remote["url"],
                remote["filename"],
                status_callback,
            )
            staged_dir = self._stage_package(
                archive_path,
                remote["version"],
                status_callback,
            )
            install_dir = self._activate_staged_install(
                staged_dir,
                remote["version"],
                status_callback,
            )
        except Exception as error:
            return self._failure_result(f"准备 ImageMagick 失败: {error}")
        finally:
            if archive_path is not None:
                self._cleanup_file(archive_path)
            self._cleanup_path_if_exists(self.staging_dir)

        return EnsureResult(
            magick_path=str(install_dir / "magick.exe"),
            version=remote["version"],
            source="private",
            updated=True,
            ready=True,
            message=f"ImageMagick 已更新到 {remote['version']}",
            fatal=False,
        )

    def _fetch_latest_package(self) -> dict:
        request = urllib.request.Request(
            ARCHIVE_INDEX_URL,
            headers={"User-Agent": "ImageC/1.0"},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            html = response.read().decode("utf-8", errors="ignore")

        architecture = self._get_architecture()
        candidates = []
        for filename, version, arch in PACKAGE_PATTERN.findall(html):
            if arch != architecture:
                continue
            candidates.append(
                {
                    "filename": filename,
                    "version": version,
                    "url": urllib.parse.urljoin(ARCHIVE_INDEX_URL, filename),
                }
            )

        if not candidates and architecture != "x64":
            for filename, version, arch in PACKAGE_PATTERN.findall(html):
                if arch == "x64":
                    candidates.append(
                        {
                            "filename": filename,
                            "version": version,
                            "url": urllib.parse.urljoin(ARCHIVE_INDEX_URL, filename),
                        }
                    )

        if not candidates:
            raise RuntimeError("未找到适用于当前系统的 ImageMagick 7.x 便携包")

        candidates.sort(key=lambda item: self._version_key(item["version"]), reverse=True)
        return candidates[0]

    def _download_package(
        self,
        url: str,
        filename: str,
        status_callback: StatusCallback | None,
    ) -> tuple[Path, str]:
        temp_dir = Path(tempfile.gettempdir()) / "imagec-imagemagick"
        temp_dir.mkdir(parents=True, exist_ok=True)
        target_path = temp_dir / filename
        request = urllib.request.Request(url, headers={"User-Agent": "ImageC/1.0"})
        digest = hashlib.sha256()

        with urllib.request.urlopen(request, timeout=30) as response, open(target_path, "wb") as file_obj:
            total = int(response.headers.get("Content-Length", "0") or "0")
            downloaded = 0
            last_report = 0.0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                file_obj.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                now = time.time()
                if status_callback and (now - last_report >= 0.5):
                    if total > 0:
                        percent = int(downloaded * 100 / total)
                        self._emit(status_callback, f"正在下载 ImageMagick... {percent}%")
                    else:
                        mb = downloaded / (1024 * 1024)
                        self._emit(status_callback, f"正在下载 ImageMagick... {mb:.1f} MB")
                    last_report = now

        self._emit(status_callback, "下载完成，准备解压...")
        return target_path, digest.hexdigest()

    def _stage_package(
        self,
        archive_path: Path,
        version: str,
        status_callback: StatusCallback | None,
    ) -> Path:
        self._emit(status_callback, "正在解压 ImageMagick...")
        self._cleanup_path_if_exists(self.staging_dir)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            if py7zr is None:
                raise RuntimeError("缺少 py7zr 依赖，无法解压官方 7z 包")
            try:
                with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                    archive.extractall(path=temp_path)
            except Exception as error:
                raise RuntimeError(f"解压 ImageMagick 失败: {error}") from error

            extracted_dir = self._find_extracted_magick_dir(temp_path)
            if extracted_dir is None:
                raise RuntimeError("解压完成，但未找到 magick.exe")

            shutil.move(str(extracted_dir), str(self.staging_dir))

        self._validate_install_dir(self.staging_dir)
        self._emit(status_callback, f"ImageMagick {version} 已完成解压校验。")
        return self.staging_dir

    def _activate_staged_install(
        self,
        staged_dir: Path,
        version: str,
        status_callback: StatusCallback | None,
    ) -> Path:
        self._emit(status_callback, "正在切换 ImageMagick 运行时...")
        self._validate_install_dir(staged_dir)

        if self.backup_dir.exists():
            self._cleanup_path(self.backup_dir)

        moved_current = False
        moved_staged = False
        try:
            if self.install_dir.exists():
                self.install_dir.rename(self.backup_dir)
                moved_current = True

            staged_dir.rename(self.install_dir)
            moved_staged = True
            self._validate_install_dir(self.install_dir)
        except Exception as error:
            if moved_staged and self.install_dir.exists():
                self._cleanup_path_if_exists(self.install_dir)
            if moved_current and self.backup_dir.exists():
                self._restore_backup_install()
            raise RuntimeError(f"切换 ImageMagick 失败: {error}") from error

        self._cleanup_path_if_exists(self.backup_dir)
        self._emit(status_callback, f"ImageMagick {version} 已准备完成。")
        return self.install_dir

    def _find_extracted_magick_dir(self, root_dir: Path) -> Path | None:
        for magick_exe in root_dir.rglob("magick.exe"):
            return magick_exe.parent
        return None

    def _resolve_install(self, install_dir: Path, source: str) -> dict | None:
        magick_path = install_dir / "magick.exe"
        if not magick_path.exists():
            return None

        return {
            "path": str(magick_path),
            "version": self._get_version(str(magick_path)),
            "source": source,
        }

    def _get_available_runtime(self) -> dict | None:
        local = self.get_local_install()
        if local:
            return local

        system_path = shutil.which("magick")
        if not system_path:
            return None

        return {
            "path": system_path,
            "version": self._get_version(system_path),
            "source": "system",
        }

    def _validate_install_dir(self, install_dir: Path) -> None:
        magick_path = install_dir / "magick.exe"
        if not install_dir.is_dir() or not magick_path.exists():
            raise RuntimeError(f"运行时目录无效: {install_dir}")

    def _repair_install_dirs(self) -> None:
        self._cleanup_path_if_exists(self.staging_dir)
        if self.backup_dir.exists():
            if self.install_dir.exists():
                self._cleanup_path(self.backup_dir)
            else:
                self._restore_backup_install()

    def _restore_backup_install(self) -> None:
        if not self.backup_dir.exists():
            return
        if self.install_dir.exists():
            return
        self.backup_dir.rename(self.install_dir)

    def _failure_result(self, message: str) -> EnsureResult:
        runtime = self._get_available_runtime()
        if runtime:
            return EnsureResult(
                magick_path=runtime["path"],
                version=runtime["version"],
                source=runtime["source"],
                updated=False,
                ready=True,
                message=f"{message}，继续使用当前可用版本。",
                fatal=False,
            )

        return EnsureResult(
            magick_path=None,
            version=None,
            source="none",
            updated=False,
            ready=False,
            message=message,
            fatal=True,
        )

    def _result_from_runtime(
        self,
        runtime: dict | None,
        updated: bool,
        message: str,
    ) -> EnsureResult:
        if runtime:
            return EnsureResult(
                magick_path=runtime["path"],
                version=runtime["version"],
                source=runtime["source"],
                updated=updated,
                ready=True,
                message=message,
                fatal=False,
            )

        return EnsureResult(
            magick_path=None,
            version=None,
            source="none",
            updated=updated,
            ready=False,
            message=message,
            fatal=True,
        )

    def _get_version(self, magick_path: str | None) -> str | None:
        if not magick_path:
            return None

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                [magick_path, "-version"],
                capture_output=True,
                text=True,
                check=False,
                creationflags=creationflags,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        match = VERSION_PATTERN.search(output)
        if match:
            return match.group(1)
        return None

    def _version_key(self, version: str) -> tuple[int, int, int, int]:
        major, minor, patch, revision = version.replace("-", ".").split(".")
        return int(major), int(minor), int(patch), int(revision)

    def _get_architecture(self) -> str:
        machine = platform.machine().lower()
        if "arm" in machine:
            return "arm64"
        if "86" in machine and "64" not in machine:
            return "x86"
        return "x64"

    def _compare_versions(self, left: str, right: str) -> int:
        left_key = self._version_key(left)
        right_key = self._version_key(right)
        if left_key < right_key:
            return -1
        if left_key > right_key:
            return 1
        return 0

    def _emit(self, callback: StatusCallback | None, message: str) -> None:
        if callback:
            callback(message)

    def _acquire_lock(self, local_available: bool) -> bool:
        deadline = time.time() + (3 if local_available else 90)
        while time.time() < deadline:
            try:
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                os.close(fd)
                return True
            except FileExistsError:
                if self._lock_is_stale():
                    self._release_lock()
                    continue
                time.sleep(0.2)
        return False

    def _lock_is_stale(self) -> bool:
        try:
            modified_at = self.lock_file.stat().st_mtime
        except FileNotFoundError:
            return False
        return (time.time() - modified_at) > 600

    def _release_lock(self) -> None:
        try:
            self.lock_file.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return

    def _cleanup_path(self, path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
            return
        if path.exists():
            path.unlink()

    def _cleanup_path_if_exists(self, path: Path) -> None:
        try:
            self._cleanup_path(path)
        except FileNotFoundError:
            return
        except OSError:
            return

    def _cleanup_file(self, file_path: Path) -> None:
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            return
