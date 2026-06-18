from __future__ import annotations

import threading
import time

from imagec.subprocess_utils import ProcessRegistry, run_command


def test_run_command_reports_cancelled_process() -> None:
    cancel_event = threading.Event()
    registry = ProcessRegistry()

    def trigger_cancel() -> None:
        time.sleep(0.2)
        cancel_event.set()

    thread = threading.Thread(target=trigger_cancel)
    thread.start()
    try:
        result = run_command(
            ["python", "-c", "import time; time.sleep(5)"],
            cancel_event=cancel_event,
            process_registry=registry,
        )
    finally:
        thread.join()

    assert result.cancelled is True
    assert result.returncode != 0
    assert registry.snapshot() == []
