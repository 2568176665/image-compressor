from __future__ import annotations

from imagec.runtime import EnsureResult, ImageMagickManager, summarize_runtime_result


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


def test_parse_candidates_supports_archive_and_github_links() -> None:
    html = """
    <a href="ImageMagick-7.1.2-23-portable-Q16-x64.7z">archive</a>
    <a href="/ImageMagick/ImageMagick/releases/download/7.1.2-23/ImageMagick-7.1.2-23-portable-Q16-HDRI-arm64.7z">github</a>
    """
    manager = ImageMagickManager()

    archive = manager._parse_candidates(
        html,
        "https://imagemagick.org/archive/binaries/",
        "x64",
    )
    github = manager._parse_candidates(html, "https://github.com", "arm64")

    assert archive[0]["url"] == (
        "https://imagemagick.org/archive/binaries/"
        "ImageMagick-7.1.2-23-portable-Q16-x64.7z"
    )
    assert github[0]["url"] == (
        "https://github.com/ImageMagick/ImageMagick/releases/download/7.1.2-23/"
        "ImageMagick-7.1.2-23-portable-Q16-HDRI-arm64.7z"
    )
