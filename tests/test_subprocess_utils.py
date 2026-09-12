from __future__ import annotations

import threading

from imagec.subprocess_utils import run_command


def test_run_command_reports_cancelled_process() -> None:
    cancel_event = threading.Event()

    def trigger_cancel() -> None:
        threading.Timer(0.2, cancel_event.set).start()

    trigger_cancel()
    result = run_command(
        ["python", "-c", "import time; time.sleep(5)"],
        cancel_event=cancel_event,
    )

    assert result.cancelled is True
    assert result.returncode != 0
