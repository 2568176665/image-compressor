from __future__ import annotations

from pathlib import Path

from build import clean, collect_garbage_paths


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
