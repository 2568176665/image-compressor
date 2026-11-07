from __future__ import annotations

from pathlib import Path

import pytest

from build import (
    ICON_FILE,
    build_codec_arguments,
    clean,
    collect_garbage_paths,
    read_icon_image_blobs,
    validate_build_output,
    validate_embedded_icon,
)


def test_collect_garbage_paths_prunes_removable_and_excluded_directories(tmp_path: Path) -> None:
    (tmp_path / "dist" / "nested").mkdir(parents=True)
    (tmp_path / "dist" / "nested" / "ignored.pyc").touch()
    (tmp_path / "src" / "nested").mkdir(parents=True)
    (tmp_path / "src" / "nested" / "module.pyc").touch()
    (tmp_path / "app.spec").touch()
    (tmp_path / "src" / "app.spec").touch()
    (tmp_path / ".codegraph").mkdir()
    (tmp_path / ".codegraph" / "ignored.pyc").touch()

    paths = collect_garbage_paths(tmp_path)

    assert tmp_path / "dist" in paths
    assert tmp_path / "src" / "nested" / "module.pyc" in paths
    assert tmp_path / "app.spec" in paths
    assert tmp_path / "src" / "app.spec" in paths
    assert tmp_path / "dist" / "nested" / "ignored.pyc" not in paths
    assert tmp_path / ".codegraph" / "ignored.pyc" not in paths

    assert clean(tmp_path) == 4
    assert not (tmp_path / "dist").exists()
    assert not (tmp_path / "src" / "nested" / "module.pyc").exists()


def test_build_dnd_arguments_are_skipped_without_dependency(monkeypatch) -> None:
    import build

    monkeypatch.setattr(build.importlib.util, "find_spec", lambda _name: None)

    assert build.build_dnd_arguments() == []


def test_build_dnd_arguments_collect_tkdnd_data(monkeypatch) -> None:
    import build

    monkeypatch.setattr(build.importlib.util, "find_spec", lambda _name: object())

    arguments = build.build_dnd_arguments()

    assert arguments[:2] == ["--collect-data", "tkinterdnd2"]
    assert "tkinterdnd2" in arguments


def test_build_codec_arguments_keeps_codec_files_as_unchanged_data() -> None:
    from build import CODEC_RESOURCE_DIR

    files = [
        CODEC_RESOURCE_DIR / "cjpegli.exe",
        CODEC_RESOURCE_DIR / "libaom.dll",
        CODEC_RESOURCE_DIR / "manifest.json",
    ]

    arguments = build_codec_arguments(files)

    assert arguments[0] == "--add-data"
    assert arguments[2] == "--add-data"
    assert arguments[4] == "--add-data"
    assert "codecs/windows-x64" in arguments[1]



def _icon_payload() -> bytes:
    return b"".join(read_icon_image_blobs(ICON_FILE))


def test_read_icon_image_blobs_parses_every_size() -> None:
    blobs = read_icon_image_blobs(ICON_FILE)

    assert len(blobs) == 7
    assert all(blobs)


def test_validate_embedded_icon_accepts_payload_with_all_sizes(tmp_path: Path) -> None:
    executable = tmp_path / "image_compressor.exe"
    executable.write_bytes(b"stub" + _icon_payload() + b"tail")

    validate_embedded_icon(executable)


def test_validate_embedded_icon_rejects_payload_missing_a_size(tmp_path: Path) -> None:
    executable = tmp_path / "image_compressor.exe"
    executable.write_bytes(b"stub" + b"".join(read_icon_image_blobs(ICON_FILE)[1:]))

    with pytest.raises(RuntimeError, match="未内嵌图标资源"):
        validate_embedded_icon(executable)


def test_validate_embedded_icon_rejects_missing_icon_file(tmp_path: Path) -> None:
    executable = tmp_path / "image_compressor.exe"
    executable.write_bytes(b"stub")

    with pytest.raises(FileNotFoundError):
        validate_embedded_icon(executable, icon_path=tmp_path / "absent.ico")


def _stage_codecs(directory: Path) -> Path:
    from build import stage_portable_codecs

    return stage_portable_codecs(directory)


def test_stage_portable_codecs_copies_whole_resource_dir(tmp_path: Path) -> None:
    from build import CODEC_PACKAGE_DIR, CODEC_RESOURCE_DIR

    target = _stage_codecs(tmp_path)

    assert target == tmp_path / CODEC_PACKAGE_DIR
    assert (target / "manifest.json").is_file()
    assert not (tmp_path / "manifest.json").exists()
    assert (target / "cjpegli.exe").read_bytes() == (
        CODEC_RESOURCE_DIR / "cjpegli.exe"
    ).read_bytes()


def test_validate_onefile_output_accepts_external_codec_dir(tmp_path: Path) -> None:
    _stage_codecs(tmp_path)
    output = tmp_path / "image_compressor.exe"
    output.write_bytes(b"stub" + _icon_payload())

    validate_build_output(output, onedir=False)


def test_validate_onefile_output_rejects_missing_external_codec_dir(tmp_path: Path) -> None:
    output = tmp_path / "image_compressor.exe"
    output.write_bytes(b"stub" + _icon_payload())

    with pytest.raises(FileNotFoundError, match="外置编码器目录缺失"):
        validate_build_output(output, onedir=False)


def test_validate_onefile_output_rejects_bundled_codec_payload(tmp_path: Path) -> None:
    _stage_codecs(tmp_path)
    output = tmp_path / "image_compressor.exe"
    output.write_bytes(b"cjpegli.exe" + _icon_payload())

    with pytest.raises(RuntimeError, match="仍内置"):
        validate_build_output(output, onedir=False)


def test_validate_onefile_output_ignores_shared_dll_names(tmp_path: Path) -> None:
    # 编码器目录里的 zlib1.dll 与 Pillow/tkinter 自带的同名 DLL 无法区分，
    # 只能以子进程入口 exe 作为"编码器是否被打进包"的判据。
    _stage_codecs(tmp_path)
    output = tmp_path / "image_compressor.exe"
    output.write_bytes(b"zlib1.dll" + _icon_payload())

    validate_build_output(output, onedir=False)


def test_build_exclude_arguments_cover_unused_heavy_modules() -> None:
    from build import EXCLUDED_MODULES, build_exclude_arguments

    arguments = build_exclude_arguments()

    assert len(arguments) == 2 * len(EXCLUDED_MODULES)
    assert arguments[:2] == ["--exclude-module", "_ssl"]
    assert "_hashlib" in EXCLUDED_MODULES


def test_validate_onefile_output_rejects_iconless_exe(tmp_path: Path) -> None:
    _stage_codecs(tmp_path)
    output = tmp_path / "image_compressor.exe"
    output.write_bytes(b"stub")

    with pytest.raises(RuntimeError, match="未内嵌图标资源"):
        validate_build_output(output, onedir=False)
