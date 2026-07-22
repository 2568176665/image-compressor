from __future__ import annotations

import concurrent.futures
import glob
import logging
import math
import os
import re
import shutil
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
VISUAL_QUALITY_PRESETS: dict[str, float | None] = {
    "关闭": None,
    "高质量 (80)": 80.0,
    "优质 (85)": 85.0,
    "视觉无损 (90)": 90.0,
}
DEFAULT_VISUAL_SCORE = VISUAL_QUALITY_PRESETS["优质 (85)"]
VISUAL_CANDIDATE_LIMIT = 8


@dataclass(slots=True)
class CompressionRequest:
    input_file: str
    output_dir: str
    target_size: int
    output_format: str
    resize_value: str | None
    min_visual_score: float | None = None


@dataclass(slots=True)
class CompressionResult:
    status: str
    message: str
    output_file: str | None = None
    output_size: int | None = None
    visual_score: float | None = None
    quality_limited: bool = False


@dataclass(frozen=True, slots=True)
class TransformPlan:
    resize_value: str | None
    scale: float | None = None


@dataclass(frozen=True, slots=True)
class VisualCandidate:
    path: Path
    size: int
    score: float


def normalize_format(value: str) -> str:
    normalized = value.strip().lower().lstrip(".")
    return "jpg" if normalized == "jpeg" else normalized


def resolve_visual_score(value: str | None) -> float | None:
    normalized = (value or "").strip()
    if normalized in VISUAL_QUALITY_PRESETS:
        return VISUAL_QUALITY_PRESETS[normalized]
    try:
        score = float(normalized)
    except ValueError:
        return DEFAULT_VISUAL_SCORE
    return score if score in VISUAL_QUALITY_PRESETS.values() else DEFAULT_VISUAL_SCORE


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
        metric_path: str | None = None,
        command_runner: Callable[..., CommandResult] = run_command,
        process_registry: ProcessRegistry | None = None,
    ) -> None:
        self.encoder_paths = {
            normalize_format(name): str(path)
            for name, path in (encoder_paths or {}).items()
        }
        self.metric_path = str(metric_path) if metric_path else None
        self.command_runner = command_runner
        self.process_registry = process_registry or ProcessRegistry()
        self.cancel_event = threading.Event()

    def set_encoder_paths(self, encoder_paths: Mapping[str, str], metric_path: str | None = None) -> None:
        self.encoder_paths = {
            normalize_format(name): str(path)
            for name, path in encoder_paths.items()
        }
        self.metric_path = str(metric_path) if metric_path else None

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
        min_visual_score: float | None = None,
        progress_callback: Callable[[int, int, CompressionResult], None] | None = None,
    ) -> str:
        self.reset()
        completed = 0
        has_failure = False
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
                        min_visual_score=min_visual_score,
                    ),
                )
                for image_file in image_files
            ]

            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result.status == "cancelled":
                    self.cancel()
                    break

                has_failure |= result.status == "failed"

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
        elif has_failure:
            status = "failed"

        return status

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

                    if request.min_visual_score is not None and self.metric_path:
                        visual_candidate = self._select_visual_candidate(
                            source_png,
                            temp_root,
                            output_format,
                            request.target_size,
                            request.min_visual_score,
                        )
                        if self.cancel_event.is_set():
                            return CompressionResult(status="cancelled", message="压缩已取消")
                        if visual_candidate:
                            try:
                                os.replace(visual_candidate.path, output_file)
                            except OSError as error:
                                logging.error("保存输出文件失败: %s", error)
                                return CompressionResult(
                                    status="failed",
                                    message=f"失败: {input_path.stem} (无法保存输出文件)",
                                )
                            return self._completed_result(
                                input_path.stem,
                                output_file,
                                visual_candidate.score,
                                quality_limited=visual_candidate.score < request.min_visual_score,
                            )

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

                    visual_score = None
                    quality_limited = False
                    if request.min_visual_score is not None and self.metric_path:
                        visual_score = self._score_candidate(source_png, candidate_output)
                        quality_limited = visual_score is None or visual_score < request.min_visual_score

                    try:
                        os.replace(candidate_output, output_file)
                    except OSError as error:
                        logging.error("保存输出文件失败: %s", error)
                        return CompressionResult(
                            status="failed",
                            message=f"失败: {input_path.stem} (无法保存输出文件)",
                        )
                    return self._completed_result(
                        input_path.stem,
                        output_file,
                        visual_score,
                        quality_limited=quality_limited,
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

    def _select_visual_candidate(
        self,
        source_png: Path,
        temp_root: Path,
        output_format: str,
        target_size: int,
        min_visual_score: float,
    ) -> VisualCandidate | None:
        candidates: list[VisualCandidate] = []
        for index, quality in enumerate(self._visual_quality_levels(output_format)[:VISUAL_CANDIDATE_LIMIT]):
            if self.cancel_event.is_set():
                return None
            candidate_path = temp_root / f"visual-{index}.{output_format}"
            candidate_path.unlink(missing_ok=True)
            if not self._encode_at_quality(source_png, candidate_path, output_format, quality):
                continue
            if not self._is_valid_image(candidate_path):
                candidate_path.unlink(missing_ok=True)
                continue
            score = self._score_candidate(source_png, candidate_path)
            if score is None:
                logging.warning("感知评分失败，回退到仅限制文件大小的压缩模式")
                return None
            candidates.append(
                VisualCandidate(path=candidate_path, size=candidate_path.stat().st_size, score=score)
            )

        eligible = [
            candidate
            for candidate in candidates
            if candidate.size <= target_size and candidate.score >= min_visual_score
        ]
        if eligible:
            return min(eligible, key=lambda candidate: candidate.size)

        limited = [candidate for candidate in candidates if candidate.size <= target_size]
        if limited:
            return max(limited, key=lambda candidate: (candidate.score, -candidate.size))
        return None

    def _visual_quality_levels(self, output_format: str) -> tuple[float | None, ...]:
        if output_format == "jpg":
            return (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)
        if output_format in {"webp", "avif"}:
            return (95, 90, 85, 80, 75, 70, 65, 60)
        if output_format == "png":
            return (None, 95, 90, 85, 80, 75, 70, 65)
        raise ValueError(f"unsupported format: {output_format}")

    def _encode_at_quality(
        self,
        source_png: Path,
        output_file: Path,
        output_format: str,
        quality: float | None,
    ) -> bool:
        encoder = self.encoder_paths[output_format]
        if output_format == "png":
            if quality is None:
                shutil.copyfile(source_png, output_file)
                oxipng_path = self.encoder_paths.get("oxipng")
                if not oxipng_path:
                    return False
                command = [oxipng_path, "-o", "2", "--strip", "all", "--force", str(output_file)]
            else:
                command = [
                    encoder,
                    f"--quality={int(quality)}-100",
                    "--speed",
                    "4",
                    "--strip",
                    "--force",
                    "--output",
                    str(output_file),
                    str(source_png),
                ]
        elif output_format == "jpg":
            command = [
                encoder,
                str(source_png),
                str(output_file),
                "--distance",
                str(quality),
                "--quiet",
            ]
        elif output_format == "webp":
            command = [
                encoder,
                "-quiet",
                "-m",
                "6",
                "-q",
                str(quality),
                "-alpha_q",
                "100",
                "-af",
                "-sharp_yuv",
                str(source_png),
                "-o",
                str(output_file),
            ]
        elif output_format == "avif":
            command = [
                encoder,
                "--speed",
                "6",
                "--jobs",
                "1",
                "--qcolor",
                str(int(quality)),
                "--qalpha",
                "100",
                str(source_png),
                str(output_file),
            ]
        else:  # pragma: no cover - guarded by SUPPORTED_FORMATS
            return False

        result = self._run_command(command)
        return not result.cancelled and result.returncode == 0 and output_file.exists()

    def _score_candidate(self, source_png: Path, candidate_path: Path) -> float | None:
        if not self.metric_path:
            return None
        comparison_path = candidate_path.with_name(f"{candidate_path.name}.score.png")
        try:
            with Image.open(source_png) as source, Image.open(candidate_path) as candidate:
                source.load()
                candidate.load()
                mode = "RGBA" if "A" in source.getbands() else "RGB"
                normalized = candidate.convert(mode)
                try:
                    normalized.save(comparison_path, format="PNG", optimize=False)
                finally:
                    normalized.close()
        except (OSError, ValueError, SyntaxError):
            comparison_path.unlink(missing_ok=True)
            return None

        result = self._run_command([self.metric_path, str(source_png), str(comparison_path)])
        comparison_path.unlink(missing_ok=True)
        if result.cancelled or result.returncode != 0:
            return None
        match = re.search(r"(?m)^\s*(-?(?:\d+\.?\d*|\.\d+))\s*$", result.stdout)
        if not match:
            return None
        return float(match.group(1))

    def _is_valid_image(self, output_file: Path) -> bool:
        try:
            with Image.open(output_file) as image:
                image.load()
        except (OSError, ValueError, SyntaxError):
            return False
        return True

    def _completed_result(
        self,
        stem: str,
        output_file: Path,
        visual_score: float | None,
        *,
        quality_limited: bool,
    ) -> CompressionResult:
        output_size = output_file.stat().st_size
        details = [f"{output_size / 1024:.1f} KB"]
        if visual_score is not None:
            details.append(f"视觉评分 {visual_score:.1f}")
        if quality_limited:
            details.append("受大小上限限制")
        return CompressionResult(
            status="completed",
            message=f"完成: {', '.join(details)} — {stem}",
            output_file=str(output_file),
            output_size=output_size,
            visual_score=visual_score,
            quality_limited=quality_limited,
        )

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
