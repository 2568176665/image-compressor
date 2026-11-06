from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

import pytest

from imagec.config import (
    DEFAULT_CONFIG,
    OUTPUT_MODE_COMPRESSED,
    OUTPUT_MODE_CUSTOM,
    OUTPUT_MODE_SIBLING,
    AppPaths,
    ConfigStore,
    configure_logging,
    normalize_output_mode,
    output_name_suffix,
    resolve_app_paths,
    resolve_output_dir,
)


def _app_paths(tmp_path: Path) -> AppPaths:
    program_dir = tmp_path / "program"
    return AppPaths(
        program_dir=program_dir,
        active_dir=program_dir,
        config_path=program_dir / "config.json",
        log_path=program_dir / "compression.log",
        legacy_config_path=None,
    )


def test_sibling_mode_outputs_next_to_source_with_suffix(tmp_path: Path) -> None:
    image_path = tmp_path / "demo.jpg"
    image_path.write_bytes(b"demo")

    assert resolve_output_dir(OUTPUT_MODE_SIBLING, str(image_path)) == str(tmp_path)
    assert output_name_suffix(OUTPUT_MODE_SIBLING) == "_ic"


def test_compressed_mode_outputs_into_compressed_subdir(tmp_path: Path) -> None:
    image_path = tmp_path / "demo.avif"

    assert resolve_output_dir(OUTPUT_MODE_COMPRESSED, str(image_path)) == str(tmp_path / "compressed")
    assert output_name_suffix(OUTPUT_MODE_COMPRESSED) == "_ic"


def test_custom_mode_uses_given_directory_without_suffix(tmp_path: Path) -> None:
    image_path = tmp_path / "demo.png"
    output_dir = tmp_path / "out"

    assert resolve_output_dir(OUTPUT_MODE_CUSTOM, str(image_path), str(output_dir)) == str(output_dir)
    assert output_name_suffix(OUTPUT_MODE_CUSTOM) == ""


def test_custom_mode_requires_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_output_dir(OUTPUT_MODE_CUSTOM, str(tmp_path / "demo.png"), "   ")


def test_normalize_output_mode_falls_back_to_compressed() -> None:
    assert normalize_output_mode("unknown") == OUTPUT_MODE_COMPRESSED
    assert normalize_output_mode(None) == OUTPUT_MODE_COMPRESSED
    assert normalize_output_mode(OUTPUT_MODE_SIBLING) == OUTPUT_MODE_SIBLING


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
        json.dumps({"target_size_kb": "321", "format": "png"}, ensure_ascii=False),
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
    assert store.load()["target_size_kb"] == "321"
    assert store.legacy_config_path == legacy_config


def test_config_round_trip_preserves_input_list_and_output_mode(tmp_path: Path) -> None:
    paths = _app_paths(tmp_path)
    store = ConfigStore(paths)
    images = [str(tmp_path / "a.jpg"), str(tmp_path / "b.png")]

    store.save(
        {
            "input_paths": images,
            "output_mode": OUTPUT_MODE_SIBLING,
            "custom_output_dir": str(tmp_path / "out"),
        }
    )

    loaded = store.load()
    assert loaded["input_paths"] == images
    assert loaded["output_mode"] == OUTPUT_MODE_SIBLING
    assert loaded["custom_output_dir"] == str(tmp_path / "out")
    assert set(DEFAULT_CONFIG).issubset(loaded)


def test_config_store_ignores_legacy_single_input_path(tmp_path: Path) -> None:
    paths = _app_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    paths.config_path.write_text(
        json.dumps({"input_path": ".\\input", "format": "png"}, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = ConfigStore(paths).load()

    assert loaded["input_paths"] == []
    assert "input_path" not in loaded


def test_config_store_coerces_tampered_input_paths(tmp_path: Path) -> None:
    paths = _app_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    paths.config_path.write_text(
        json.dumps({"input_paths": "C:\\only\\one.jpg"}, ensure_ascii=False),
        encoding="utf-8",
    )

    assert ConfigStore(paths).load()["input_paths"] == ["C:\\only\\one.jpg"]

    paths.config_path.write_text(json.dumps({"input_paths": {"a": 1}}), encoding="utf-8")
    assert ConfigStore(paths).load()["input_paths"] == []


def test_config_store_uses_defaults_when_file_missing(tmp_path: Path) -> None:
    paths = AppPaths(
        program_dir=tmp_path / "program",
        active_dir=tmp_path / "program",
        config_path=tmp_path / "program" / "config.json",
        log_path=tmp_path / "program" / "compression.log",
        legacy_config_path=None,
    )
    store = ConfigStore(paths)

    loaded = store.load()

    assert loaded["target_size_kb"] == "100"
    assert loaded["format"] == "jpg"
    assert loaded["max_workers"] == "4"
    assert loaded["overwrite"] is False


def test_config_round_trip_preserves_user_settings(tmp_path: Path) -> None:
    paths = AppPaths(
        program_dir=tmp_path / "program",
        active_dir=tmp_path / "program",
        config_path=tmp_path / "program" / "config.json",
        log_path=tmp_path / "program" / "compression.log",
        legacy_config_path=None,
    )
    store = ConfigStore(paths)

    store.save({"target_size_kb": "250", "max_workers": "8", "overwrite": True})

    loaded = store.load()
    assert loaded["target_size_kb"] == "250"
    assert loaded["max_workers"] == "8"
    assert loaded["overwrite"] is True
    assert set(DEFAULT_CONFIG).issubset(loaded)


def test_config_store_ignores_unknown_legacy_fields(tmp_path: Path) -> None:
    paths = AppPaths(
        program_dir=tmp_path / "program",
        active_dir=tmp_path / "program",
        config_path=tmp_path / "program" / "config.json",
        log_path=tmp_path / "program" / "compression.log",
        legacy_config_path=None,
    )
    paths.config_path.parent.mkdir(parents=True)
    paths.config_path.write_text(
        json.dumps({"visual_quality": "优质 (85)", "resize_width": "10"}),
        encoding="utf-8",
    )

    loaded = ConfigStore(paths).load()

    assert "visual_quality" not in loaded
    assert "resize_width" not in loaded


def test_configure_logging_uses_rotating_handler(tmp_path: Path) -> None:
    paths = AppPaths(
        program_dir=tmp_path,
        active_dir=tmp_path,
        config_path=tmp_path / "config.json",
        log_path=tmp_path / "compression.log",
        legacy_config_path=None,
    )

    configure_logging(paths)
    logger = logging.getLogger()
    handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]
    try:
        assert handlers, "expected a rotating file handler"
        assert handlers[0].maxBytes > 0
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
