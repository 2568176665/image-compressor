from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path

import pytest

from imagec.config import (
    DEFAULT_CONFIG,
    OUTPUT_MODE_CUSTOM,
    OUTPUT_MODE_LABELS,
    OUTPUT_MODE_SIBLING,
    AppPaths,
    ConfigStore,
)
from imagec.ui import ImageCompressorApp, create_root


class _StubRuntimeManager:
    def ensure_codecs_ready(self):  # pragma: no cover - 测试里不触发编码器检查
        raise AssertionError("tests must not run the codec check")


def _app_paths(tmp_path: Path) -> AppPaths:
    program_dir = tmp_path / "program"
    return AppPaths(
        program_dir=program_dir,
        active_dir=program_dir,
        config_path=program_dir / "config.json",
        log_path=program_dir / "compression.log",
        legacy_config_path=None,
    )


def _make_root() -> tk.Tk:
    try:
        root = create_root()
    except Exception as error:  # pragma: no cover - 无图形环境时跳过
        pytest.skip(f"Tk 不可用: {error}")
    root.withdraw()
    return root


def _make_app(monkeypatch, tmp_path: Path, paths: AppPaths | None = None):
    monkeypatch.setattr(ImageCompressorApp, "start_runtime_check", lambda self: None)
    root = _make_root()
    app = ImageCompressorApp(
        root,
        config_store=ConfigStore(paths or _app_paths(tmp_path)),
        runtime_manager=_StubRuntimeManager(),
    )
    return root, app


def test_ui_collects_multiple_images_and_persists_them(monkeypatch, tmp_path: Path) -> None:
    root, app = _make_app(monkeypatch, tmp_path)
    try:
        first = tmp_path / "a.jpg"
        second = tmp_path / "b.png"
        first.write_bytes(b"x")
        second.write_bytes(b"x")

        app.add_paths([str(first), str(second), str(first), str(tmp_path / "missing.jpg")])

        assert app.input_paths == [str(first), str(second)]
        assert app.input_listbox.size() == 2

        app.output_mode_var.set(OUTPUT_MODE_LABELS[OUTPUT_MODE_SIBLING])
        app.save_config()
    finally:
        root.destroy()

    saved = json.loads(_app_paths(tmp_path).config_path.read_text(encoding="utf-8"))
    assert saved["input_paths"] == [str(first), str(second)]
    assert saved["output_mode"] == OUTPUT_MODE_SIBLING


def test_add_button_matches_sibling_buttons_and_opens_menu(monkeypatch, tmp_path: Path) -> None:
    root, app = _make_app(monkeypatch, tmp_path)
    try:
        assert isinstance(app.add_button, tk.Button)
        for option in ("relief", "bd", "font", "width", "padx", "highlightthickness"):
            assert app.add_button.cget(option) == app.remove_button.cget(option), option

        labels = [
            app.add_menu.entrycget(index, "label")
            for index in range(app.add_menu.index("end") + 1)
        ]
        assert labels == ["选择图片（可多选）", "选择文件夹"]

        popup_calls: list[tuple[int, int]] = []
        monkeypatch.setattr(app.add_menu, "tk_popup", lambda x, y: popup_calls.append((x, y)))
        monkeypatch.setattr(app.add_menu, "grab_release", lambda: None)

        app.add_button.invoke()

        assert len(popup_calls) == 1
    finally:
        root.destroy()


def test_ui_custom_output_entry_toggles_with_output_mode(monkeypatch, tmp_path: Path) -> None:
    root, app = _make_app(monkeypatch, tmp_path)
    try:
        assert str(app.custom_output_entry["state"]) == "disabled"
        app.output_mode_var.set(OUTPUT_MODE_LABELS[OUTPUT_MODE_CUSTOM])
        app.update_custom_output_state()
        assert str(app.custom_output_entry["state"]) == "normal"
        assert str(app.custom_output_button["state"]) == "normal"
    finally:
        root.destroy()


def test_ui_restores_only_existing_paths_from_config(monkeypatch, tmp_path: Path) -> None:
    paths = _app_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    existing = tmp_path / "kept.jpg"
    existing.write_bytes(b"x")
    paths.config_path.write_text(
        json.dumps(
            {
                "input_paths": [str(existing), str(tmp_path / "gone.jpg")],
                "output_mode": OUTPUT_MODE_SIBLING,
                "custom_output_dir": "",
                "target_size_kb": "100",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    root, app = _make_app(monkeypatch, tmp_path, paths)
    try:
        assert app.input_paths == [str(existing)]
        assert app.input_listbox.size() == 1
        assert app.current_output_mode() == OUTPUT_MODE_SIBLING
        assert app.size_entry.get() == "100"
        assert app.format_var.get() == str(DEFAULT_CONFIG["format"])
    finally:
        root.destroy()
