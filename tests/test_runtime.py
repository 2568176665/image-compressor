from __future__ import annotations

import hashlib
import json
from pathlib import Path

from imagec.runtime import (
    CODEC_EXECUTABLES,
    CodecRuntimeManager,
    EnsureResult,
    summarize_runtime_result,
    validate_codec_resources,
)


def _write_manifest(root: Path) -> None:
    files: dict[str, str] = {}
    for executable in sorted({*CODEC_EXECUTABLES.values(), "ssimulacra2.exe"}):
        path = root / executable
        path.write_bytes(executable.encode("ascii"))
        files[executable] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "LICENSE.txt").write_text("license", encoding="utf-8")
    files["LICENSE.txt"] = hashlib.sha256((root / "LICENSE.txt").read_bytes()).hexdigest()
    manifest = {
        "platform": "windows-x64",
        "encoders": CODEC_EXECUTABLES,
        "metrics": {"ssimulacra2": "ssimulacra2.exe"},
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_summarize_runtime_result_marks_fatal_failure() -> None:
    result = EnsureResult(
        encoder_paths={},
        versions={},
        source="none",
        ready=False,
        message="missing codecs",
        fatal=True,
    )

    summary = summarize_runtime_result(result)

    assert summary.level == "error"
    assert summary.can_start is False


def test_summarize_runtime_result_marks_ready_bundle() -> None:
    result = EnsureResult(
        encoder_paths={"jpg": "cjpegli.exe"},
        versions={"jpg": "0.11.2"},
        source="bundled",
        ready=True,
        message="ready",
    )

    summary = summarize_runtime_result(result)

    assert summary.level == "info"
    assert summary.can_start is True


def test_validate_codec_resources_detects_tampering(tmp_path: Path) -> None:
    _write_manifest(tmp_path)

    files = validate_codec_resources(tmp_path)

    assert tmp_path / "manifest.json" in files
    assert tmp_path / "cjpegli.exe" in files

    (tmp_path / "cjpegli.exe").write_bytes(b"tampered")
    try:
        validate_codec_resources(tmp_path)
    except RuntimeError as error:
        assert "校验失败" in str(error)
    else:  # pragma: no cover
        raise AssertionError("tampered resource was accepted")


def test_validate_codec_resources_accepts_windows_text_line_endings(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    license_path = tmp_path / "LICENSE.txt"
    license_path.write_bytes(b"license\r\nline\r\n")

    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["LICENSE.txt"] = hashlib.sha256(b"license\nline\n").hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    validate_codec_resources(tmp_path)


def test_runtime_resolves_all_encoders_and_checks_pillow(tmp_path: Path, monkeypatch) -> None:
    _write_manifest(tmp_path)
    manager = CodecRuntimeManager(resource_dir=str(tmp_path))
    monkeypatch.setattr(manager, "_is_supported_platform", lambda: True)
    monkeypatch.setattr(manager, "_pillow_supports_avif", lambda: True)
    monkeypatch.setattr(manager, "_get_version", lambda _path: "test-version")

    result = manager.ensure_codecs_ready()

    assert result.ready is True
    assert result.source == "bundled"
    assert set(result.encoder_paths) == {"jpg", "png", "oxipng", "webp", "avif"}
    assert set(result.versions) == set(result.encoder_paths)
    assert result.metric_path == str((tmp_path / "ssimulacra2.exe").resolve())


def test_runtime_allows_older_bundle_without_visual_metric(tmp_path: Path, monkeypatch) -> None:
    _write_manifest(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("metrics")
    manifest["files"].pop("ssimulacra2.exe")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    manager = CodecRuntimeManager(resource_dir=str(tmp_path))
    monkeypatch.setattr(manager, "_is_supported_platform", lambda: True)
    monkeypatch.setattr(manager, "_pillow_supports_avif", lambda: True)
    monkeypatch.setattr(manager, "_get_version", lambda _path: "test-version")

    result = manager.ensure_codecs_ready()

    assert result.ready is True
    assert result.metric_path is None
    assert "仅限制文件大小" in result.message


def test_runtime_fails_when_manifest_is_missing(tmp_path: Path, monkeypatch) -> None:
    manager = CodecRuntimeManager(resource_dir=str(tmp_path))
    monkeypatch.setattr(manager, "_is_supported_platform", lambda: True)

    result = manager.ensure_codecs_ready()

    assert result.ready is False
    assert result.fatal is True
    assert "清单" in result.message


def test_runtime_keeps_encoder_ready_log_without_progress_logs(
    tmp_path: Path, monkeypatch
) -> None:
    _write_manifest(tmp_path)
    manager = CodecRuntimeManager(resource_dir=str(tmp_path))
    monkeypatch.setattr(manager, "_is_supported_platform", lambda: True)
    monkeypatch.setattr(manager, "_pillow_supports_avif", lambda: True)
    monkeypatch.setattr(manager, "_get_version", lambda _path: "test-version")
    messages: list[str] = []

    result = manager.ensure_codecs_ready(status_callback=messages.append)

    assert result.ready is True
    assert messages == []
    assert result.message.startswith("编码器已就绪:")
