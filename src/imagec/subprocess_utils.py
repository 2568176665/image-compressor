from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    cancelled: bool


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            return


def run_command(
    command: list[str],
    *,
    cancel_event: threading.Event | None = None,
) -> CommandResult:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )
    while True:
        if cancel_event and cancel_event.is_set():
            terminate_process(process)
            stdout, stderr = process.communicate()
            return CommandResult(
                returncode=process.returncode or -1,
                stdout=stdout,
                stderr=stderr,
                cancelled=True,
            )
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            return CommandResult(
                returncode=process.returncode or 0,
                stdout=stdout,
                stderr=stderr,
                cancelled=False,
            )
        time.sleep(0.05)
