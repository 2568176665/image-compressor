from __future__ import annotations

import concurrent.futures
import glob
import logging
import math
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from PIL import Image, ImageOps

from .subprocess_utils import CommandResult, ProcessRegistry, run_command


SUPPORTED_FORMATS = ("jpg", "png", "webp", "avif")
IMAGE_SUFFIXES = ("jpg", "jpeg", "png", "webp", "avif")
IMAGE_PATTERNS = tuple(f"*.{suffix}" for suffix in IMAGE_SUFFIXES) + tuple(
    f"*.{suffix.upper()}" for suffix in IMAGE_SUFFIXES
)
DEFAULT_MAX_WORKERS_CAP = 4
RESIZE_PATTERN = re.compile(r"^\s*(?P<width>\d*)\s*x\s*(?P<height>\d*)\s*$", re.IGNORECASE)
PERCENT_PATTERN = re.compile(r"^\s*(?P<percent>\d+(?:\.\d+)?)\s*%\s*$")


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


@dataclass(frozen=True, slots=True)
class TransformPlan:
    resize_value: str | None
    scale: float | None = None


def normalize_format(value: str) -> str:
    normalized = value.strip().lower().lstrip(".")
    return "jpg" if normalized == "jpeg" else normalized


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
        encoder_paths: Mapping[str, str] | None,
        command_runner: Callable[..., CommandResult] = run_command,
        process_registry: ProcessRegistry | None = None,
    ) -> None:
        self.encoder_paths = {
            normalize_format(name): str(path)
            for name, path in (encoder_paths or {}).items()
        }
        self.command_runner = command_runner
        self.process_registry = process_registry or ProcessRegistry()
        self.cancel_event = threading.Event()

    def set_encoder_paths(self, encoder_paths: Mapping[str, str]) -> None:
        self.encoder_paths = {
            normalize_format(name): str(path)
            for name, path in encoder_paths.items()
        }

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
        output_format = normalize_format(request.output_format)
        output_file = output_dir / f"{input_path.stem}.{output_format}"

        if output_format not in SUPPORTED_FORMATS:
            return CompressionResult(status="failed", message=f"失败: 不支持的输出格式 {output_format}")
        if not self.encoder_paths.get(output_format):
            return CompressionResult(
                status="failed",
                message=f"失败: {input_path.stem} (缺少 {output_format} 编码器)",
            )
        if request.target_size <= 0:
            return CompressionResult(status="failed", message=f"失败: {input_path.stem} (目标大小无效)")

        try:
            input_size = input_path.stat().st_size
        except OSError:
            return CompressionResult(status="failed", message=f"失败: {input_path.stem} (无法读取文件)")

        try:
            base_image = self._load_image(input_path)
        except (OSError, ValueError, SyntaxError) as error:
            logging.error("读取图片失败: %s", error)
            return CompressionResult(status="failed", message=f"失败: {input_path.stem} (无法读取图片)")

        try:
            plans = self._build_resize_chain(request.resize_value, input_size, request.target_size)
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return CompressionResult(
                    status="failed",
                    message=f"失败: {input_path.stem} (无法创建输出目录)",
                )
            with tempfile.TemporaryDirectory(prefix="imagec-", dir=output_dir) as temp_dir:
                temp_root = Path(temp_dir)
                for index, plan in enumerate(plans):
                    if self.cancel_event.is_set():
                        return CompressionResult(status="cancelled", message="压缩已取消")

                    source_png = temp_root / f"source-{index}.png"
                    candidate_output = temp_root / f"output.{output_format}"
                    candidate_output.unlink(missing_ok=True)
                    try:
                        self._save_transform(base_image, plan, output_format, source_png)
                    except (OSError, ValueError, SyntaxError) as error:
                        logging.error("生成临时 PNG 失败: %s", error)
                        continue

                    try:
                        result = self._encode(
                            source_png,
                            candidate_output,
                            output_format,
                            request.target_size,
                        )
                    except (OSError, ValueError, KeyError) as error:
                        logging.error("调用编码器失败: %s", error)
                        candidate_output.unlink(missing_ok=True)
                        result = CompressionResult(
                            status="failed",
                            message=f"失败: {input_path.stem} (编码器执行失败)",
                        )
                    if result.status == "cancelled":
                        return result
                    if result.status != "completed":
                        continue

                    try:
                        os.replace(candidate_output, output_file)
                    except OSError as error:
                        logging.error("保存输出文件失败: %s", error)
                        return CompressionResult(
                            status="failed",
                            message=f"失败: {input_path.stem} (无法保存输出文件)",
                        )
                    return CompressionResult(
                        status="completed",
                        message=f"完成: {input_path.stem}",
                        output_file=str(output_file),
                    )
        finally:
            base_image.close()

        return CompressionResult(status="failed", message=f"失败: {input_path.stem} (无法达到目标)")

    def _load_image(self, input_path: Path) -> Image.Image:
        with Image.open(input_path) as source:
            oriented = ImageOps.exif_transpose(source)
            oriented.load()
            return oriented.copy()

    def _save_transform(
        self,
        base_image: Image.Image,
        plan: TransformPlan,
        output_format: str,
        target_path: Path,
    ) -> None:
        image = base_image.copy()
        working = image
        try:
            working = self._apply_resize(image, plan)
            converted = self._convert_for_output(working, output_format)
            try:
                converted.save(target_path, format="PNG", optimize=False)
            finally:
                converted.close()
        finally:
            if working is not image:
                working.close()
            image.close()

    def _apply_resize(self, image: Image.Image, plan: TransformPlan) -> Image.Image:
        percent = self._parse_percent(plan.resize_value)
        if percent is not None:
            width = max(1, round(image.width * percent / 100))
            height = max(1, round(image.height * percent / 100))
            image = image.resize((width, height), Image.Resampling.LANCZOS, reducing_gap=3.0)

        geometry = self._parse_resize(plan.resize_value)
        if geometry:
            width, height = geometry
            image.thumbnail(
                (width or image.width, height or image.height),
                Image.Resampling.LANCZOS,
                reducing_gap=3.0,
            )

        if plan.scale is not None and plan.scale < 1:
            width = max(1, round(image.width * plan.scale))
            height = max(1, round(image.height * plan.scale))
            return image.resize((width, height), Image.Resampling.LANCZOS, reducing_gap=3.0)
        return image

    def _convert_for_output(self, image: Image.Image, output_format: str) -> Image.Image:
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        if output_format == "jpg":
            if has_alpha:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                alpha = rgba.getchannel("A")
                try:
                    background.paste(rgba, mask=alpha)
                finally:
                    alpha.close()
                    rgba.close()
                return background
            return image.convert("RGB")

        if output_format in {"png", "webp", "avif"}:
            if has_alpha:
                return image.convert("RGBA")
            return image.convert("RGB")

        raise ValueError(f"unsupported format: {output_format}")

    def _encode(
        self,
        source_png: Path,
        output_file: Path,
        output_format: str,
        target_size: int,
    ) -> CompressionResult:
        encoder = self.encoder_paths[output_format]
        if output_format == "png":
            return self._encode_png(encoder, source_png, output_file, target_size)

        command = self._build_encoder_command(
            encoder,
            source_png,
            output_file,
            output_format,
            target_size,
        )
        return self._run_and_validate(command, output_file, target_size)

    def _encode_png(
        self,
        pngquant_path: str,
        source_png: Path,
        output_file: Path,
        target_size: int,
    ) -> CompressionResult:
        oxipng_path = self.encoder_paths.get("oxipng")
        if not oxipng_path:
            return CompressionResult(status="failed", message="失败: 缺少 oxipng 编码器")

        quality_ranges = ((60, 100), (60, 90), (60, 80), (60, 70), (60, 60))
        for minimum, maximum in quality_ranges:
            output_file.unlink(missing_ok=True)
            pngquant_command = [
                pngquant_path,
                f"--quality={minimum}-{maximum}",
                "--speed",
                "4",
                "--strip",
                "--force",
                "--output",
                str(output_file),
                str(source_png),
            ]
            command_result = self._run_command(pngquant_command)
            if command_result.cancelled:
                output_file.unlink(missing_ok=True)
                return CompressionResult(status="cancelled", message="压缩已取消")
            if command_result.returncode != 0 or not output_file.exists():
                continue

            # pngquant 已经去除了元数据并满足目标大小时，无需再启动 oxipng。
            # oxipng 只在量化结果仍超标时负责进一步压缩。
            try:
                if output_file.stat().st_size <= target_size:
                    result = self._validate_output_file(output_file, target_size)
                    if result.status == "completed":
                        return result
                    continue
            except OSError:
                continue

            oxipng_command = [
                oxipng_path,
                "-o",
                "2",
                "--strip",
                "all",
                "--threads",
                "1",
                "--force",
                str(output_file),
            ]
            result = self._run_and_validate(oxipng_command, output_file, target_size)
            if result.status in {"completed", "cancelled"}:
                return result

        output_file.unlink(missing_ok=True)
        return CompressionResult(status="failed", message=f"失败: {output_file.stem} (无法达到目标)")

    def _build_encoder_command(
        self,
        encoder: str,
        source_png: Path,
        output_file: Path,
        output_format: str,
        target_size: int,
    ) -> list[str]:
        if output_format == "jpg":
            return [
                encoder,
                str(source_png),
                str(output_file),
                "--target_size",
                str(target_size),
                "--quiet",
            ]
        if output_format == "webp":
            return [
                encoder,
                "-quiet",
                "-m",
                "6",
                "-pass",
                "10",
                "-size",
                str(target_size),
                str(source_png),
                "-o",
                str(output_file),
            ]
        if output_format == "avif":
            return [
                encoder,
                "--speed",
                "6",
                "--jobs",
                "1",
                "--target-size",
                str(target_size),
                str(source_png),
                str(output_file),
            ]
        raise ValueError(f"unsupported format: {output_format}")

    def _run_and_validate(
        self,
        command: list[str],
        output_file: Path,
        target_size: int,
    ) -> CompressionResult:
        result = self._run_command(command)
        if result.cancelled:
            output_file.unlink(missing_ok=True)
            return CompressionResult(status="cancelled", message="压缩已取消")
        if result.returncode != 0:
            logging.error("命令执行失败: %s", result.stderr)
            output_file.unlink(missing_ok=True)
            return CompressionResult(status="failed", message=f"失败: {output_file.stem} (命令执行失败)")

        return self._validate_output_file(output_file, target_size)

    def _validate_output_file(self, output_file: Path, target_size: int) -> CompressionResult:
        if not output_file.exists():
            return CompressionResult(status="failed", message=f"失败: {output_file.stem} (未生成输出文件)")

        try:
            with Image.open(output_file) as image:
                image.load()
        except (OSError, ValueError, SyntaxError) as error:
            logging.error("输出图片校验失败: %s", error)
            output_file.unlink(missing_ok=True)
            return CompressionResult(status="failed", message=f"失败: {output_file.stem} (输出文件无效)")

        if output_file.stat().st_size <= target_size:
            return CompressionResult(
                status="completed",
                message=f"完成: {output_file.stem}",
                output_file=str(output_file),
            )

        output_file.unlink(missing_ok=True)
        return CompressionResult(status="failed", message=f"失败: {output_file.stem} (无法达到目标)")

    def _run_command(self, command: list[str]) -> CommandResult:
        return self.command_runner(
            command,
            cancel_event=self.cancel_event,
            process_registry=self.process_registry,
        )

    def _build_resize_chain(
        self,
        resize_value: str | None,
        input_size: int,
        target_size: int,
    ) -> list[TransformPlan]:
        requested_resize = (
            resize_value
            if self._parse_resize(resize_value) or self._parse_percent(resize_value) is not None
            else None
        )
        plans = [TransformPlan(requested_resize)]
        base_scale = max(0.15, min(0.95, math.sqrt(target_size / max(input_size, 1))))
        for factor in (1.0, 0.92, 0.84, 0.76, 0.68):
            plan = TransformPlan(requested_resize, max(0.1, base_scale * factor))
            if plan not in plans:
                plans.append(plan)
        return plans

    def _parse_resize(self, value: str | None) -> tuple[int | None, int | None] | None:
        if not value:
            return None
        match = RESIZE_PATTERN.match(value)
        if not match:
            return None
        width = int(match.group("width")) if match.group("width") else None
        height = int(match.group("height")) if match.group("height") else None
        if width is None and height is None:
            return None
        if width is not None and width <= 0:
            return None
        if height is not None and height <= 0:
            return None
        return width, height

    def _parse_percent(self, value: str | None) -> float | None:
        if not value:
            return None
        match = PERCENT_PATTERN.match(value)
        if not match:
            return None
        percent = float(match.group("percent"))
        if percent <= 0:
            return None
        return percent
