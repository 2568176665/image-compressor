from __future__ import annotations

import concurrent.futures
import glob
import logging
import math
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .subprocess_utils import CommandResult, ProcessRegistry, run_command


IMAGE_PATTERNS = ("*.jpg", "*.jpeg", "*.png", "*.webp")
DEFAULT_MAX_WORKERS_CAP = 4


@dataclass(slots=True)
class CompressionRequest:
    input_file: str
    output_dir: str
    target_size: int
    output_format: str
    resize_value: str | None


@dataclass(slots=True)
class CompressionResult:
    status: str
    message: str
    output_file: str | None = None


@dataclass(slots=True)
class CompressionSummary:
    status: str
    completed: int
    total: int
    results: list[CompressionResult]


def resolve_max_workers(value: str | None) -> int:
    normalized = (value or "").strip()
    if normalized and normalized != "0":
        try:
            parsed = int(normalized)
        except ValueError:
            parsed = 0
        if parsed > 0:
            return parsed

    cpu_count = os.cpu_count() or 1
    return max(1, min(cpu_count, DEFAULT_MAX_WORKERS_CAP))


def collect_image_files(input_path: str) -> list[str] | None:
    if os.path.isfile(input_path):
        return [input_path]

    if os.path.isdir(input_path):
        image_files: list[str] = []
        for pattern in IMAGE_PATTERNS:
            image_files.extend(glob.glob(os.path.join(input_path, pattern)))
        return sorted(set(image_files))

    return None


class CompressionService:
    def __init__(
        self,
        *,
        magick_path: str | None,
        command_runner: Callable[..., CommandResult] = run_command,
        process_registry: ProcessRegistry | None = None,
    ) -> None:
        self.magick_path = magick_path
        self.command_runner = command_runner
        self.process_registry = process_registry or ProcessRegistry()
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.process_registry.terminate_all()

    def reset(self) -> None:
        self.cancel_event.clear()

    def run_batch(
        self,
        image_files: list[str],
        *,
        output_dir: str,
        target_size: int,
        output_format: str,
        resize_value: str | None,
        max_workers: int,
        progress_callback: Callable[[int, int, CompressionResult], None] | None = None,
    ) -> CompressionSummary:
        self.reset()
        completed = 0
        results: list[CompressionResult] = []
        total = len(image_files)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self.compress_file,
                    CompressionRequest(
                        input_file=image_file,
                        output_dir=output_dir,
                        target_size=target_size,
                        output_format=output_format,
                        resize_value=resize_value,
                    ),
                )
                for image_file in image_files
            ]

            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                if result.status == "cancelled":
                    self.cancel()
                    break

                completed += 1
                if progress_callback:
                    progress_callback(completed, total, result)

                if self.cancel_event.is_set():
                    break

            if self.cancel_event.is_set():
                for future in futures:
                    future.cancel()

        status = "completed"
        if self.cancel_event.is_set():
            status = "cancelled"
        elif any(result.status == "failed" for result in results):
            status = "failed"

        return CompressionSummary(status=status, completed=completed, total=total, results=results)

    def compress_file(self, request: CompressionRequest) -> CompressionResult:
        if self.cancel_event.is_set():
            return CompressionResult(status="cancelled", message="压缩已取消")

        input_path = Path(request.input_file)
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{input_path.stem}.{request.output_format}"

        if not self.magick_path:
            return CompressionResult(status="failed", message=f"失败: {input_path.stem} (缺少 ImageMagick)")

        if self._can_copy_without_recompression(request, output_file):
            shutil.copy2(input_path, output_file)
            return CompressionResult(
                status="copied",
                message=f"已复制: {input_path.stem}",
                output_file=str(output_file),
            )

        if request.output_format in {"jpg", "jpeg"}:
            fast_result = self._run_and_validate(
                self._build_jpeg_extent_command(request, output_file),
                output_file,
                request.target_size,
            )
            if fast_result.status in {"completed", "cancelled"}:
                return fast_result

        if request.output_format == "png":
            return self._compress_png(request, output_file)

        return self._compress_with_quality_search(request, output_file)

    def _can_copy_without_recompression(
        self,
        request: CompressionRequest,
        output_file: Path,
    ) -> bool:
        input_path = Path(request.input_file)
        if request.resize_value:
            return False

        suffix = input_path.suffix.lower().lstrip(".")
        normalized_suffix = "jpg" if suffix == "jpeg" else suffix
        normalized_format = "jpg" if request.output_format == "jpeg" else request.output_format
        if normalized_suffix != normalized_format:
            return False

        try:
            return input_path.stat().st_size <= request.target_size
        except OSError:
            return False

    def _compress_png(self, request: CompressionRequest, output_file: Path) -> CompressionResult:
        input_size = Path(request.input_file).stat().st_size
        resize_chain = self._build_png_resize_chain(request.resize_value, input_size, request.target_size)

        for resize_steps in resize_chain:
            command = [self.magick_path, request.input_file]
            for geometry in resize_steps:
                command.extend(["-resize", geometry])
            command.extend(
                [
                    "-strip",
                    "-define",
                    "png:compression-level=9",
                    "-define",
                    "png:compression-filter=5",
                    str(output_file),
                ]
            )
            result = self._run_and_validate(command, output_file, request.target_size)
            if result.status in {"completed", "cancelled"}:
                return result

        return CompressionResult(status="failed", message=f"失败: {Path(request.input_file).stem} (无法达到目标)")

    def _compress_with_quality_search(
        self,
        request: CompressionRequest,
        output_file: Path,
    ) -> CompressionResult:
        try:
            original_size = Path(request.input_file).stat().st_size
        except OSError:
            return CompressionResult(status="failed", message=f"失败: {Path(request.input_file).stem} (无法读取文件大小)")

        current_quality = self._initial_quality(original_size, request.target_size)
        low, high = 0, 100
        best_quality: int | None = None
        best_output_written = False

        for _ in range(6):
            command = self._build_quality_command(request, output_file, current_quality)
            result = self._run_and_validate(command, output_file, request.target_size)
            if result.status == "cancelled":
                return result
            if result.status == "completed":
                best_quality = current_quality
                best_output_written = True
                low = current_quality + 1
            else:
                high = current_quality - 1
                best_output_written = False

            current_quality = (low + high) // 2
            if low > high:
                break

        if best_quality is None:
            return CompressionResult(status="failed", message=f"失败: {Path(request.input_file).stem} (无法达到目标)")

        if not best_output_written:
            final_command = self._build_quality_command(request, output_file, best_quality)
            result = self._run_and_validate(final_command, output_file, request.target_size)
            if result.status != "completed":
                return result

        return CompressionResult(
            status="completed",
            message=f"完成: {Path(request.input_file).stem}",
            output_file=str(output_file),
        )

    def _run_and_validate(
        self,
        command: list[str],
        output_file: Path,
        target_size: int,
    ) -> CompressionResult:
        result = self.command_runner(
            command,
            cancel_event=self.cancel_event,
            process_registry=self.process_registry,
        )
        if result.cancelled:
            return CompressionResult(status="cancelled", message="压缩已取消")
        if result.returncode != 0:
            logging.error("命令执行失败: %s", result.stderr)
            return CompressionResult(status="failed", message=f"失败: {output_file.stem} (命令执行失败)")

        if output_file.exists() and output_file.stat().st_size <= target_size:
            return CompressionResult(
                status="completed",
                message=f"完成: {output_file.stem}",
                output_file=str(output_file),
            )

        if output_file.exists():
            output_file.unlink(missing_ok=True)
        return CompressionResult(status="failed", message=f"失败: {output_file.stem} (无法达到目标)")

    def _build_jpeg_extent_command(self, request: CompressionRequest, output_file: Path) -> list[str]:
        target_kb = max(1, request.target_size // 1024)
        command = [self.magick_path, request.input_file]
        if request.resize_value:
            command.extend(["-resize", request.resize_value])
        command.extend(["-strip", "-define", f"jpeg:extent={target_kb}kb", str(output_file)])
        return command

    def _build_quality_command(
        self,
        request: CompressionRequest,
        output_file: Path,
        quality: int,
    ) -> list[str]:
        command = [self.magick_path, request.input_file]
        if request.resize_value:
            command.extend(["-resize", request.resize_value])
        command.append("-strip")
        command.extend(["-quality", str(max(1, quality)), str(output_file)])
        return command

    def _build_png_resize_chain(
        self,
        resize_value: str | None,
        input_size: int,
        target_size: int,
    ) -> list[list[str]]:
        steps: list[list[str]] = []
        base_steps = [resize_value] if resize_value else []
        if input_size <= target_size:
            steps.append([step for step in base_steps if step])
            return steps

        base_scale = int(max(15, min(95, math.sqrt(target_size / input_size) * 100)))
        for factor in (100, 92, 84, 76, 68):
            scaled = max(10, int(base_scale * factor / 100))
            geometry = f"{scaled}%"
            candidate = [step for step in base_steps if step]
            candidate.append(geometry)
            if candidate not in steps:
                steps.append(candidate)
        if base_steps and base_steps not in steps:
            steps.append(base_steps)
        return steps

    def _initial_quality(self, original_size: int, target_size: int) -> int:
        ratio = target_size / original_size
        if ratio >= 0.8:
            return 95
        if ratio >= 0.5:
            return 80
        if ratio >= 0.2:
            return 60
        return 40
