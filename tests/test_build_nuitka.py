from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_N_PATH = PROJECT_ROOT / "build-N.py"


def _load_build_n() -> ModuleType:
    if "build_N" in sys.modules:
        return sys.modules["build_N"]

    spec = importlib.util.spec_from_file_location("build_N", BUILD_N_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_N"] = module
    spec.loader.exec_module(module)
    return module


def _option_values(command: list[str], option: str) -> list[str]:
    prefix = f"{option}="
    return [item[len(prefix) :] for item in command if item.startswith(prefix)]


def test_build_command_keeps_codecs_as_raw_dir() -> None:
    command = _load_build_n().build_command("0.2.0", onefile=False)

    assert any(item.startswith("--include-raw-dir=") for item in command)
    assert not any(item.startswith("--include-data-dir=") for item in command)
    raw_dir = _option_values(command, "--include-raw-dir")[0]
    assert raw_dir.endswith("=codecs/windows-x64")


def test_build_command_uses_numeric_file_version() -> None:
    command = _load_build_n().build_command("0.2.0", onefile=False)

    assert _option_values(command, "--file-version") == ["0.2.0.0"]
    assert _option_values(command, "--product-version") == ["0.2.0.0"]


def test_build_command_selects_mode() -> None:
    module = _load_build_n()

    assert _option_values(module.build_command("0.2.0", onefile=False), "--mode") == ["standalone"]
    assert _option_values(module.build_command("0.2.0", onefile=True), "--mode") == ["onefile"]


def test_build_outputs_are_separated_from_pyinstaller() -> None:
    module = _load_build_n()

    assert module.OUTPUT_DIR.name == "nuitka-dist"
    assert module.dist_folder_name(onefile=False) != module.dist_folder_name(onefile=True)
    assert module.standalone_dir() == module.OUTPUT_DIR / "image_compressor.dist"


def test_build_command_omits_tk_inter_plugin_without_tcl_dir(monkeypatch) -> None:
    module = _load_build_n()
    monkeypatch.setattr(module, "find_tcl_library_dir", lambda: None)

    assert "--enable-plugin=tk-inter" not in module.build_command("0.2.0", onefile=False)


def test_build_command_enables_tk_inter_plugin_with_tcl_dir(monkeypatch, tmp_path: Path) -> None:
    module = _load_build_n()
    tcl_dir = tmp_path / "tcl" / "tcl9.0"
    tcl_dir.mkdir(parents=True)
    (tcl_dir / "init.tcl").touch()
    monkeypatch.setattr(module, "find_tcl_library_dir", lambda: tcl_dir)

    command = module.build_command("0.2.0", onefile=False)

    assert "--enable-plugin=tk-inter" in command
    assert _option_values(command, "--tcl-library-dir") == [str(tcl_dir)]


def test_find_tcl_library_dir_detects_embedded_tcl(tmp_path: Path, monkeypatch) -> None:
    module = _load_build_n()
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "base"))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))

    assert module.find_tcl_library_dir() is None

    tcl_dir = tmp_path / "base" / "tcl" / "tcl8.6"
    tcl_dir.mkdir(parents=True)
    (tcl_dir / "init.tcl").touch()

    assert module.find_tcl_library_dir() == tcl_dir
