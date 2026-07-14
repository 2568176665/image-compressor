from __future__ import annotations

import tkinter as tk

from .config import ConfigStore, configure_logging, resolve_app_paths
from .runtime import CodecRuntimeManager
from .ui import ImageCompressorApp


def main() -> int:
    paths = resolve_app_paths()
    configure_logging(paths)
    root = tk.Tk()
    ImageCompressorApp(
        root,
        config_store=ConfigStore(paths),
        runtime_manager=CodecRuntimeManager(base_dir=str(paths.program_dir)),
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
