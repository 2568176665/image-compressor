from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image, features

from imagec.compression import (
    SUPPORTED_FORMATS,
    CompressionRequest,
    CompressionResult,
    CompressionService,
    TransformPlan,
    collect_image_files,
    resolve_max_workers,
)
from imagec.subprocess_utils import CommandResult, ProcessRegistry, run_command


def _write_image(path: Path, *, mode: str = "RGB", size: tuple[int, int] = (64, 48)) -> None:
    color = (40, 120, 220, 128) if mode == "RGBA" else (40, 120, 220)
    image = Image.new(mode, size, color)
    image.save(path)
    image.close()


def _fake_encoder_runner(calls: list[list[str]], *, oversize_once: bool = False):
    state = {"oversize": oversize_once}

    def runner(command: list[str], **_kwargs) -> CommandResult:
        calls.append(command)
        if "--output" in command:
            output_path = Path(command[command.index("--output") + 1])
        elif len(command) > 2 and Path(command[2]).suffix.lower() == ".jpg":
            output_path = Path(command[2])
        else:
            output_path = Path(command[-1])

        if output_path.suffix.lower() == ".jpg":
            image_format = "JPEG"
            mode = "RGB"
        elif output_path.suffix.lower() == ".avif":
            image_format = "AVIF"
            mode = "RGBA"
        elif output_path.suffix.lower() == ".webp":
            image_format = "WEBP"
            mode = "RGBA"
        else:
            image_format = "PNG"
            mode = "RGBA"

        size = (1024, 1024) if state["oversize"] else (8, 8)
        is_oversize = state["oversize"]
        state["oversize"] = False
        if is_oversize:
            image = Image.effect_noise(size, 100).convert(mode)
        else:
            image = Image.new(mode, size, (40, 120, 220, 128) if mode == "RGBA" else (40, 120, 220))
        save_options = {"quality": 95} if image_format in {"JPEG", "WEBP", "AVIF"} else {}
        image.save(output_path, format=image_format, **save_options)
        image.close()
        return CommandResult(returncode=0, stdout="", stderr="", cancelled=False)

    return runner


def _service(calls: list[list[str]], *, oversize_once: bool = False) -> CompressionService:
    return CompressionService(
        encoder_paths={name: f"{name}.exe" for name in SUPPORTED_FORMATS} | {"oxipng": "oxipng.exe"},
        command_runner=_fake_encoder_runner(calls, oversize_once=oversize_once),
    )


def test_resolve_max_workers_uses_safe_default(monkeypatch) -> None:
    monkeypatch.setattr("imagec.compression.os.cpu_count", lambda: 16)

    assert resolve_max_workers("0") == 4


def test_resolve_max_workers_accepts_user_override(monkeypatch) -> None:
    monkeypatch.setattr("imagec.compression.os.cpu_count", lambda: 2)

    assert resolve_max_workers("9") == 9


def test_collect_image_files_includes_avif_and_is_case_insensitive(tmp_path: Path) -> None:
    folder = tmp_path / "input"
    folder.mkdir()
    for name in ("b.PNG", "a.jpg", "d.jpeg", "c.avif", "a.jpg", "ignore.txt"):
        (folder / name).write_bytes(b"x")

    result = collect_image_files(str(folder))

    assert result == [
        str(folder / "a.jpg"),
        str(folder / "b.PNG"),
        str(folder / "c.avif"),
        str(folder / "d.jpeg"),
    ]


def test_percent_resize_is_applied_with_lanczos(tmp_path: Path) -> None:
    source = Image.new("RGB", (80, 60), (40, 120, 220))
    service = _service([])

    resized = service._apply_resize(source, TransformPlan("50%"))

    assert resized.size == (40, 30)
    resized.close()
    source.close()


def test_jpeg_encoder_command_and_transparent_pixels_use_white_background(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _write_image(source, mode="RGBA", size=(16, 16))
    output_dir = tmp_path / "out"
    calls: list[list[str]] = []

    def runner(command: list[str], **_kwargs) -> CommandResult:
        calls.append(command)
        source_png = Path(command[1])
        output_path = Path(command[2])
        with Image.open(source_png) as prepared:
            assert prepared.mode == "RGB"
            red, green, blue = prepared.getpixel((0, 0))
            assert red > 140 and green > 180 and blue > 230
            prepared.save(output_path, format="JPEG")
        return CommandResult(returncode=0, stdout="", stderr="", cancelled=False)

    service = CompressionService(encoder_paths={"jpg": "cjpegli.exe"}, command_runner=runner)
    result = service.compress_file(
        CompressionRequest(str(source), str(output_dir), 20_000, "jpg", None)
    )

    assert result.status == "completed"
    assert calls[0][0] == "cjpegli.exe"
    assert output_dir in Path(calls[0][1]).parents
    assert "--target_size" in calls[0]
    assert Path(result.output_file).suffix == ".jpg"


def test_webp_and_avif_encoder_commands_have_target_size_options(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _write_image(source)

    for output_format, expected_flag in (("webp", "-size"), ("avif", "--target-size")):
        calls: list[list[str]] = []
        service = _service(calls)
        result = service.compress_file(
            CompressionRequest(str(source), str(tmp_path / output_format), 20_000, output_format, None)
        )

        assert result.status == "completed"
        assert expected_flag in calls[0]
        assert Path(result.output_file).suffix == f".{output_format}"


def test_png_skips_oxipng_when_quantized_output_meets_target(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _write_image(source, mode="RGBA")
    calls: list[list[str]] = []
    service = _service(calls)

    result = service.compress_file(
        CompressionRequest(str(source), str(tmp_path / "out"), 20_000, "png", None)
    )

    assert result.status == "completed"
    assert calls[0][0] == "png.exe"
    assert "--quality=60-100" in calls[0]
    assert calls[0][calls[0].index("--speed") + 1] == "4"
    assert not any(command[0] == "oxipng.exe" for command in calls)


def test_png_uses_fast_oxipng_only_when_quantized_output_is_oversized(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _write_image(source, mode="RGBA")
    output_dir = tmp_path / "out"
    calls: list[list[str]] = []

    def runner(command: list[str], **_kwargs) -> CommandResult:
        calls.append(command)
        if command[0] == "png.exe":
            output_path = Path(command[command.index("--output") + 1])
            image = Image.effect_noise((128, 128), 100).convert("RGBA")
            image.save(output_path, format="PNG")
            image.close()
        else:
            output_path = Path(command[-1])
            image = Image.new("RGBA", (8, 8), (40, 120, 220, 128))
            image.save(output_path, format="PNG")
            image.close()
        return CommandResult(returncode=0, stdout="", stderr="", cancelled=False)

    service = CompressionService(
        encoder_paths={"png": "png.exe", "oxipng": "oxipng.exe"},
        command_runner=runner,
    )
    result = service.compress_file(
        CompressionRequest(str(source), str(output_dir), 500, "png", None)
    )

    assert result.status == "completed"
    oxipng = next(command for command in calls if command[0] == "oxipng.exe")
    assert oxipng[1:3] == ["-o", "2"]
    assert "-Z" not in oxipng


def test_resize_retry_keeps_final_output_within_target(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _write_image(source)
    calls: list[list[str]] = []
    service = _service(calls, oversize_once=True)

    result = service.compress_file(
        CompressionRequest(str(source), str(tmp_path / "out"), 500, "webp", None)
    )

    assert result.status == "completed"
    assert len(calls) >= 2
    assert Path(result.output_file).stat().st_size <= 500


def test_failed_encoding_cleans_temporary_output_and_does_not_create_final_file(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _write_image(source)
    output_dir = tmp_path / "out"

    def failed_runner(command: list[str], **_kwargs) -> CommandResult:
        if "--output" in command:
            output_path = Path(command[command.index("--output") + 1])
        elif len(command) > 2 and Path(command[2]).suffix.lower() == ".jpg":
            output_path = Path(command[2])
        else:
            output_path = Path(command[-1])
        output_path.write_bytes(b"invalid")
        return CommandResult(returncode=0, stdout="", stderr="", cancelled=False)

    service = CompressionService(encoder_paths={"jpg": "cjpegli.exe"}, command_runner=failed_runner)
    result = service.compress_file(
        CompressionRequest(str(source), str(output_dir), 500, "jpg", None)
    )

    assert result.status == "failed"
    assert not (output_dir / "source.jpg").exists()


@pytest.mark.skipif(not features.check("avif"), reason="Pillow AVIF codec is unavailable")
def test_pillow_can_round_trip_avif_input(tmp_path: Path) -> None:
    source = tmp_path / "source.avif"
    image = Image.new("RGB", (32, 24), (20, 80, 140))
    image.save(source, format="AVIF", quality=70, speed=6, max_threads=1)
    image.close()

    with Image.open(source) as decoded:
        decoded.load()
        assert decoded.size == (32, 24)


def test_run_batch_reports_cancelled_status(tmp_path: Path) -> None:
    files = []
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    for index in range(3):
        file_path = tmp_path / f"file-{index}.jpg"
        _write_image(file_path)
        files.append(str(file_path))

    service = _service([])

    def fake_compress(request: CompressionRequest):
        if request.input_file.endswith("file-0.jpg"):
            service.cancel()
        return CompressionResult(status="completed", message=Path(request.input_file).name)

    service.compress_file = fake_compress  # type: ignore[method-assign]

    summary = service.run_batch(
        files,
        output_dir=str(output_dir),
        target_size=500,
        output_format="jpg",
        resize_value=None,
        max_workers=2,
    )

    assert summary.status == "cancelled"
    assert summary.total == 3
    assert summary.completed <= 2


def test_cancel_terminates_running_external_process() -> None:
    registry = ProcessRegistry()
    cancel_event = threading.Event()
    result_holder: dict[str, CommandResult] = {}

    def run() -> None:
        result_holder["result"] = run_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cancel_event=cancel_event,
            process_registry=registry,
        )

    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 5
    while not registry.snapshot() and time.monotonic() < deadline:
        time.sleep(0.02)

    cancel_event.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert result_holder["result"].cancelled is True
    assert registry.snapshot() == []
