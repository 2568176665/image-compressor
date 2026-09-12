from __future__ import annotations

from pathlib import Path

from build import build_codec_arguments, clean, validate_build_output


def test_clean_removes_ignored_artifacts(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("build/\n*.pyc\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("x = 1\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "old.pyc").touch()
    (tmp_path / "src" / "keep.pyc").touch()

    removed = clean(tmp_path)

    assert removed >= 2
    assert not (tmp_path / "build").exists()
    assert not (tmp_path / "src" / "keep.pyc").exists()
    assert (tmp_path / "src" / "keep.py").exists()


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
