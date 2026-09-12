from __future__ import annotations

from pathlib import Path

from build import build_codec_arguments, clean, collect_garbage_paths, validate_build_output


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


def test_validate_onefile_output_checks_embedded_codec_names(tmp_path: Path) -> None:
    from build import CODEC_RESOURCE_DIR, validate_codec_resources

    output = tmp_path / "image_compressor.exe"
    names = " ".join(path.name for path in validate_codec_resources(CODEC_RESOURCE_DIR))
    output.write_bytes(names.encode("utf-8"))

    validate_build_output(output, onedir=False)
