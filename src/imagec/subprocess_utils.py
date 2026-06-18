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


class ProcessRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: list[subprocess.Popen[str]] = []

    def register(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes.append(process)

    def unregister(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._processes = [item for item in self._processes if item is not process]

    def snapshot(self) -> list[subprocess.Popen[str]]:
        with self._lock:
            return list(self._processes)

    def terminate_all(self) -> None:
        for process in self.snapshot():
            terminate_process(process)


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
    cwd: str | None = None,
    timeout: float | None = None,
    cancel_event: threading.Event | None = None,
    process_registry: ProcessRegistry | None = None,
) -> CommandResult:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )
    registry = process_registry or ProcessRegistry()
    registry.register(process)
    start = time.monotonic()
    try:
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
            if timeout is not None and (time.monotonic() - start) > timeout:
                terminate_process(process)
                stdout, stderr = process.communicate()
                return CommandResult(
                    returncode=process.returncode or -1,
                    stdout=stdout,
                    stderr=(stderr or "") + "\nCommand timed out.",
                    cancelled=False,
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
    finally:
        registry.unregister(process)
