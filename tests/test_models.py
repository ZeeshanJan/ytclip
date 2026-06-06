import pytest

from ytclip.models import (
    extract_video_id,
    format_time,
    generate_filename,
    parse_time,
)


@pytest.mark.parametrize("s,expected", [
    ("0", 0.0),
    ("90", 90.0),
    ("1:30", 90.0),
    ("0:01:30", 90.0),
    ("1:01:30", 3690.0),
    ("2:30", 150.0),
    ("10:00", 600.0),
])
def test_parse_time(s, expected):
    assert parse_time(s) == pytest.approx(expected)


def test_parse_time_invalid():
    with pytest.raises(ValueError):
        parse_time("not-a-time")


@pytest.mark.parametrize("seconds,expected", [
    (0, "0:00"),
    (90, "1:30"),
    (3600, "1:00:00"),
    (3661, "1:01:01"),
    (599, "9:59"),
])
def test_format_time(seconds, expected):
    assert format_time(seconds) == expected


@pytest.mark.parametrize("url,expected_id", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
])
def test_extract_video_id(url, expected_id):
    assert extract_video_id(url) == expected_id


def test_extract_video_id_invalid():
    assert extract_video_id("https://example.com") is None
    assert extract_video_id("not-a-url") is None


def test_generate_filename():
    name = generate_filename(
        template="{title}_{start}-{end}_{id}",
        title="My Cool Video",
        start=90.0,
        end=150.0,
        job_id="abcdef1234567890",
        ext="mp4",
    )
    assert name == "My_Cool_Video_0130-0230_abcdef12.mp4"


def test_generate_filename_special_chars():
    name = generate_filename(
        template="{title}_{start}-{end}_{id}",
        title="Video: With / Special <Chars>",
        start=0.0,
        end=30.0,
        job_id="abc123",
        ext="mkv",
    )
    assert ".mkv" in name
    assert "/" not in name
    assert "<" not in name
    assert ">" not in name
