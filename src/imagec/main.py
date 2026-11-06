from __future__ import annotations

import ctypes
import os

from .config import ConfigStore, configure_logging, resolve_app_paths
from .runtime import CodecRuntimeManager
from .ui import ImageCompressorApp, create_root


def enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            return


def main() -> int:
    enable_dpi_awareness()
    paths = resolve_app_paths()
    configure_logging(paths)
    root = create_root()
    ImageCompressorApp(
        root,
        config_store=ConfigStore(paths),
        runtime_manager=CodecRuntimeManager(base_dir=str(paths.program_dir)),
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
