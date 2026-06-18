from __future__ import annotations

from imagec.runtime import EnsureResult, summarize_runtime_result


def test_summarize_runtime_result_marks_fatal_failure() -> None:
    result = EnsureResult(
        magick_path=None,
        version=None,
        source="none",
        updated=False,
        ready=False,
        message="missing runtime",
        fatal=True,
    )

    summary = summarize_runtime_result(result)

    assert summary.level == "error"
    assert summary.can_start is False


def test_summarize_runtime_result_marks_fallback_warning() -> None:
    result = EnsureResult(
        magick_path="C:/magick.exe",
        version="7.1.2-23",
        source="system",
        updated=False,
        ready=True,
        message="using system runtime",
        fatal=False,
    )

    summary = summarize_runtime_result(result)

    assert summary.level == "warning"
    assert summary.can_start is True
