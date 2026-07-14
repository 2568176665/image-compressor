from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, features

from imagec.compression import CompressionRequest, CompressionService
from imagec.runtime import CodecRuntimeManager, validate_codec_resources


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "src" / "third_party" / "codecs" / "windows-x64"
SMOKE_AVAILABLE = os.name == "nt" and RESOURCE_DIR.is_dir() and features.check("avif")


@pytest.mark.skipif(not SMOKE_AVAILABLE, reason="Windows x64 bundled codec resources are unavailable")
def test_bundled_codecs_smoke_with_rgb_alpha_and_avif_input(tmp_path: Path) -> None:
    validate_codec_resources(RESOURCE_DIR)
    runtime_result = CodecRuntimeManager(resource_dir=str(RESOURCE_DIR)).ensure_codecs_ready()
    assert runtime_result.ready is True

    service = CompressionService(encoder_paths=runtime_result.encoder_paths)
    rgb = tmp_path / "rgb.png"
    transparent = tmp_path / "transparent.png"
    avif = tmp_path / "input.avif"
    Image.new("RGB", (320, 240), (40, 120, 220)).save(rgb)
    Image.new("RGBA", (320, 240), (40, 120, 220, 128)).save(transparent)
    with Image.open(rgb) as image:
        image.save(avif, format="AVIF", quality=70, speed=6, max_threads=1)

    for source in (rgb, transparent, avif):
        for output_format in ("jpg", "png", "webp", "avif"):
            result = service.compress_file(
                CompressionRequest(
                    input_file=str(source),
                    output_dir=str(tmp_path / output_format),
                    target_size=50_000,
                    output_format=output_format,
                    resize_value=None,
                )
            )
            assert result.status == "completed", result.message
            output = Path(result.output_file)
            assert output.stat().st_size <= 50_000
            with Image.open(output) as encoded:
                encoded.load()
