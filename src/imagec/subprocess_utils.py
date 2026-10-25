from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    cancelled: bool
    timed_out: bool = False


@dataclass(slots=True)
class _OutputBuffer:
    chunks: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, text: str) -> None:
        with self.lock:
            self.chunks.append(text)

    def read(self) -> str:
        with self.lock:
            return "".join(self.chunks)


def _drain(stream, buffer: _OutputBuffer) -> None:
    try:
        for chunk in iter(stream.readline, ""):
            buffer.append(chunk)
    except (OSError, ValueError):
        return
    finally:
        stream.close()


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
    timeout: float | None = None,
) -> CommandResult:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )

    stdout_buffer = _OutputBuffer()
    stderr_buffer = _OutputBuffer()
    drainers = [
        threading.Thread(target=_drain, args=(process.stdout, stdout_buffer), daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, stderr_buffer), daemon=True),
    ]
    for drainer in drainers:
        drainer.start()

    deadline = time.monotonic() + timeout if timeout else None
    cancelled = False
    timed_out = False

    while True:
        if cancel_event and cancel_event.is_set():
            cancelled = True
            terminate_process(process)
            break
        if deadline is not None and time.monotonic() > deadline:
            timed_out = True
            terminate_process(process)
            break
        if process.poll() is not None:
            break
        time.sleep(0.05)

    for drainer in drainers:
        drainer.join(timeout=5)

    returncode = process.returncode if process.returncode is not None else -1
    return CommandResult(
        returncode=returncode,
        stdout=stdout_buffer.read(),
        stderr=stderr_buffer.read(),
        cancelled=cancelled,
        timed_out=timed_out,
    )
