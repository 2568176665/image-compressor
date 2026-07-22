from __future__ import annotations

import json
from pathlib import Path

from imagec.config import AppPaths, ConfigStore, derive_output_path, resolve_app_paths


def test_derive_output_path_from_empty_input() -> None:
    assert derive_output_path("") == ".\\output"


def test_derive_output_path_from_file_path(tmp_path: Path) -> None:
    image_path = tmp_path / "demo.jpg"
    image_path.write_bytes(b"demo")

    assert derive_output_path(str(image_path)) == str(tmp_path / "output")


def test_derive_output_path_from_avif_path(tmp_path: Path) -> None:
    image_path = tmp_path / "demo.avif"

    assert derive_output_path(str(image_path)) == str(tmp_path / "output")


def test_resolve_app_paths_prefers_program_dir_when_writable(tmp_path: Path) -> None:
    program_dir = tmp_path / "program"
    fallback_dir = tmp_path / "fallback"

    paths = resolve_app_paths(program_dir=program_dir, fallback_root=fallback_dir)

    assert paths.active_dir == program_dir
    assert paths.config_path == program_dir / "config.json"
    assert paths.log_path == program_dir / "compression.log"


def test_resolve_app_paths_falls_back_when_program_dir_not_writable(
    monkeypatch, tmp_path: Path
) -> None:
    program_dir = tmp_path / "program"
    fallback_dir = tmp_path / "fallback"

    monkeypatch.setattr("imagec.config.is_directory_writable", lambda _path: False)

    paths = resolve_app_paths(program_dir=program_dir, fallback_root=fallback_dir)

    assert paths.active_dir == fallback_dir / "ImageC"
    assert paths.config_path == fallback_dir / "ImageC" / "config.json"
    assert paths.log_path == fallback_dir / "ImageC" / "compression.log"


def test_config_store_reads_legacy_program_config_and_saves_to_fallback(
    monkeypatch, tmp_path: Path
) -> None:
    program_dir = tmp_path / "program"
    program_dir.mkdir()
    fallback_root = tmp_path / "fallback"
    legacy_config = program_dir / "config.json"
    legacy_config.write_text(
        json.dumps({"input_path": ".\\input", "format": "png"}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "imagec.config.is_directory_writable",
        lambda path: path != program_dir,
    )

    paths = resolve_app_paths(program_dir=program_dir, fallback_root=fallback_root)
    store = ConfigStore(paths)

    loaded = store.load()
    loaded["format"] = "webp"
    store.save(loaded)

    saved = json.loads(paths.config_path.read_text(encoding="utf-8"))
    assert loaded["format"] == "webp"
    assert saved["format"] == "webp"
    assert store.load()["input_path"] == ".\\input"
    assert store.legacy_config_path == legacy_config


def test_config_store_uses_defaults_when_file_missing(tmp_path: Path) -> None:
    paths = AppPaths(
        program_dir=tmp_path / "program",
        fallback_dir=tmp_path / "fallback",
        active_dir=tmp_path / "program",
        config_path=tmp_path / "program" / "config.json",
        log_path=tmp_path / "program" / "compression.log",
        legacy_config_path=None,
    )
    store = ConfigStore(paths)

    loaded = store.load()

    assert loaded["target_size_kb"] == "100"
    assert loaded["format"] == "jpg"
    assert loaded["visual_quality"] == "优质 (85)"
