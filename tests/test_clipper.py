import pytest

from ytclip.clipper import _build_format_string
from ytclip.models import OutputFormat


@pytest.mark.parametrize("fmt,quality,expected_parts", [
    (OutputFormat.MP4, "best", ["bestvideo+bestaudio"]),
    (OutputFormat.MKV, "best", ["bestvideo+bestaudio"]),
    (OutputFormat.MP3, "best", ["bestaudio"]),
    (OutputFormat.AAC, "best", ["bestaudio"]),
    (OutputFormat.MP4, "1080p", ["height<=1080"]),
    (OutputFormat.MP4, "720p", ["height<=720"]),
    (OutputFormat.MP4, "4k", ["height<=2160"]),
])
def test_build_format_string(fmt, quality, expected_parts):
    result = _build_format_string(fmt, quality)
    for part in expected_parts:
        assert part in result


def test_format_string_audio_ignores_quality():
    # Audio formats should always use bestaudio regardless of quality setting
    mp3_best = _build_format_string(OutputFormat.MP3, "best")
    mp3_1080 = _build_format_string(OutputFormat.MP3, "1080p")
    assert mp3_best == mp3_1080
    assert "bestaudio" in mp3_best
