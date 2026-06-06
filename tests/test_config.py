import tempfile
import textwrap
from pathlib import Path

import pytest

from ytclip.config import _parse_config, load_config, Config


def test_defaults():
    cfg = _parse_config({})
    assert cfg.general.max_concurrent_jobs == 2
    assert cfg.general.max_clip_duration == 0
    assert cfg.quality.max_quality == "best"
    assert cfg.quality.prefer_segments_only is False
    assert cfg.output.default_format == "mp4"
    assert cfg.auth.enabled is False
    assert cfg.ytdlp.auto_update is True
    assert cfg.ytdlp.auto_update_interval_hours == 24
    assert cfg.server.port == 8000


def test_partial_override():
    raw = {
        "general": {"max_concurrent_jobs": 4, "log_level": "debug"},
        "quality": {"max_quality": "1080p"},
    }
    cfg = _parse_config(raw)
    assert cfg.general.max_concurrent_jobs == 4
    assert cfg.general.log_level == "DEBUG"
    assert cfg.quality.max_quality == "1080p"
    assert cfg.server.port == 8000  # unchanged


def test_load_from_file():
    toml = textwrap.dedent("""
        [general]
        max_concurrent_jobs = 3
        output_dir = "/tmp/ytclip-test"

        [auth]
        enabled = true
        password = "secret"
    """)
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write(toml)
        f.flush()
        cfg = load_config(f.name)

    assert cfg.general.max_concurrent_jobs == 3
    assert cfg.general.output_dir == Path("/tmp/ytclip-test")
    assert cfg.auth.enabled is True
    assert cfg.auth.password == "secret"


def test_data_dir_and_db_path():
    cfg = Config()
    assert cfg.db_path.name == "ytclip.db"
    assert cfg.data_dir.name == ".ytclip"
