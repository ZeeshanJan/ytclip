"""
Integration tests — require network access and ffmpeg.
Run with: pytest --integration (or pytest -m integration)
"""
import tempfile
import uuid
from pathlib import Path

import pytest

from ytclip.clipper import create_clip, setup_ffmpeg
from ytclip.models import OutputFormat

# A short public-domain clip on YouTube
TEST_URL = "https://www.youtube.com/watch?v=BaW_jenozKc"  # 10-second test video by YouTube
TEST_START = 1.0
TEST_END = 5.0


@pytest.fixture(autouse=True)
def setup():
    setup_ffmpeg()


@pytest.mark.integration
async def test_create_mp4_clip():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        progress_log = []

        def cb(pct, msg):
            progress_log.append((pct, msg))

        output_path, title = await create_clip(
            job_id=str(uuid.uuid4()),
            url=TEST_URL,
            start_time=TEST_START,
            end_time=TEST_END,
            output_format=OutputFormat.MP4,
            quality="best",
            include_subtitles=False,
            output_dir=out_dir,
            filename_template="{title}_{start}-{end}_{id}",
            cookies_file="",
            prefer_segments_only=False,
            progress_cb=cb,
        )

        assert output_path.exists()
        assert output_path.suffix == ".mp4"
        assert output_path.stat().st_size > 1000
        assert len(progress_log) > 0
        assert progress_log[-1][0] == 100


@pytest.mark.integration
async def test_create_audio_clip():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)

        output_path, _ = await create_clip(
            job_id=str(uuid.uuid4()),
            url=TEST_URL,
            start_time=TEST_START,
            end_time=TEST_END,
            output_format=OutputFormat.MP3,
            quality="best",
            include_subtitles=False,
            output_dir=out_dir,
            filename_template="{title}_{start}-{end}_{id}",
            cookies_file="",
            prefer_segments_only=False,
            progress_cb=lambda p, m: None,
        )

        assert output_path.exists()
        assert output_path.suffix == ".mp3"
        assert output_path.stat().st_size > 100
