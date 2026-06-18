from __future__ import annotations

from pathlib import Path

from imagec.compression import (
    CompressionRequest,
    CompressionService,
    collect_image_files,
    resolve_max_workers,
)


def test_resolve_max_workers_uses_safe_default(monkeypatch) -> None:
    monkeypatch.setattr("imagec.compression.os.cpu_count", lambda: 16)

    assert resolve_max_workers("0") == 4


def test_resolve_max_workers_accepts_user_override(monkeypatch) -> None:
    monkeypatch.setattr("imagec.compression.os.cpu_count", lambda: 2)

    assert resolve_max_workers("9") == 9


def test_collect_image_files_returns_sorted_unique_matches(tmp_path: Path) -> None:
    folder = tmp_path / "input"
    folder.mkdir()
    for name in ("b.png", "a.jpg", "a.jpg"):
        (folder / name).write_bytes(b"x")

    result = collect_image_files(str(folder))

    assert result == [str(folder / "a.jpg"), str(folder / "b.png")]


def test_compress_file_copies_when_no_recompression_needed(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"1234")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    service = CompressionService(magick_path="magick")
    request = CompressionRequest(
        input_file=str(source),
        output_dir=str(output_dir),
        target_size=100,
        output_format="jpg",
        resize_value=None,
    )

    result = service.compress_file(request)

    assert result.status == "copied"
    assert (output_dir / "source.jpg").read_bytes() == b"1234"


def test_compress_file_for_png_uses_dimension_control_before_compression(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"x" * 4000)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    calls: list[list[str]] = []

    def fake_runner(command: list[str], **_kwargs):
        calls.append(command)
        output_path = Path(command[-1])
        output_path.write_bytes(b"x" * 300)
        from imagec.subprocess_utils import CommandResult

        return CommandResult(returncode=0, stdout="", stderr="", cancelled=False)

    service = CompressionService(magick_path="magick", command_runner=fake_runner)
    request = CompressionRequest(
        input_file=str(source),
        output_dir=str(output_dir),
        target_size=500,
        output_format="png",
        resize_value=None,
    )

    result = service.compress_file(request)

    assert result.status == "completed"
    assert any("-resize" in command for command in calls)
    assert any("png:compression-level=9" in part for command in calls for part in command)


def test_run_batch_reports_cancelled_status(tmp_path: Path) -> None:
    files = []
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    for index in range(3):
        file_path = tmp_path / f"file-{index}.jpg"
        file_path.write_bytes(b"x" * 1024)
        files.append(str(file_path))

    service = CompressionService(magick_path="magick")

    def fake_compress(request: CompressionRequest):
        if request.input_file.endswith("file-0.jpg"):
            service.cancel()
        from imagec.compression import CompressionResult

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
