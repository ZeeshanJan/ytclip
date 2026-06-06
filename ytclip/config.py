from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_CONFIG_PATHS = [
    Path("config.toml"),
    Path.home() / ".ytclip" / "config.toml",
    Path("/config/config.toml"),  # Docker volume
]

_config: Config | None = None


@dataclass
class GeneralConfig:
    output_dir: Path = field(default_factory=lambda: Path.home() / "yt-clips")
    max_clip_duration: int = 0
    max_concurrent_jobs: int = 2
    log_level: str = "INFO"
    log_file: str = ""


@dataclass
class QualityConfig:
    max_quality: str = "best"
    prefer_segments_only: bool = False


@dataclass
class OutputConfig:
    filename_template: str = "{title}_{start}-{end}_{id}"
    default_format: str = "mp4"
    include_subtitles: bool = False


@dataclass
class AuthConfig:
    enabled: bool = False
    password: str = ""


@dataclass
class YtdlpConfig:
    auto_update: bool = True
    auto_update_interval_hours: int = 24
    cookies_file: str = ""


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000


@dataclass
class PlatformConfig:
    client_id: str = ""
    client_secret: str = ""


@dataclass
class PlatformsConfig:
    youtube: PlatformConfig = field(default_factory=PlatformConfig)
    instagram: PlatformConfig = field(default_factory=PlatformConfig)
    tiktok: PlatformConfig = field(default_factory=PlatformConfig)
    linkedin: PlatformConfig = field(default_factory=PlatformConfig)


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    ytdlp: YtdlpConfig = field(default_factory=YtdlpConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    platforms: PlatformsConfig = field(default_factory=PlatformsConfig)
    public_url: str = "http://localhost:8000"

    @property
    def data_dir(self) -> Path:
        d = Path.home() / ".ytclip"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ytclip.db"


def _parse_config(raw: dict) -> Config:
    cfg = Config()

    if g := raw.get("general"):
        cfg.general.output_dir = Path(g.get("output_dir", cfg.general.output_dir)).expanduser()
        cfg.general.max_clip_duration = int(g.get("max_clip_duration", cfg.general.max_clip_duration))
        cfg.general.max_concurrent_jobs = int(g.get("max_concurrent_jobs", cfg.general.max_concurrent_jobs))
        cfg.general.log_level = g.get("log_level", cfg.general.log_level).upper()
        cfg.general.log_file = g.get("log_file", cfg.general.log_file)

    if q := raw.get("quality"):
        cfg.quality.max_quality = q.get("max_quality", cfg.quality.max_quality)
        cfg.quality.prefer_segments_only = bool(q.get("prefer_segments_only", cfg.quality.prefer_segments_only))

    if o := raw.get("output"):
        cfg.output.filename_template = o.get("filename_template", cfg.output.filename_template)
        cfg.output.default_format = o.get("default_format", cfg.output.default_format)
        cfg.output.include_subtitles = bool(o.get("include_subtitles", cfg.output.include_subtitles))

    if a := raw.get("auth"):
        cfg.auth.enabled = bool(a.get("enabled", cfg.auth.enabled))
        cfg.auth.password = a.get("password", cfg.auth.password)

    if y := raw.get("ytdlp"):
        cfg.ytdlp.auto_update = bool(y.get("auto_update", cfg.ytdlp.auto_update))
        cfg.ytdlp.auto_update_interval_hours = int(y.get("auto_update_interval_hours", cfg.ytdlp.auto_update_interval_hours))
        cfg.ytdlp.cookies_file = y.get("cookies_file", cfg.ytdlp.cookies_file)

    if s := raw.get("server"):
        cfg.server.host = s.get("host", cfg.server.host)
        cfg.server.port = int(s.get("port", cfg.server.port))

    cfg.public_url = raw.get("public_url", cfg.public_url).rstrip("/")

    if p := raw.get("platforms"):
        for name in ("youtube", "instagram", "tiktok", "linkedin"):
            if pc := p.get(name):
                platform_cfg = getattr(cfg.platforms, name)
                platform_cfg.client_id = pc.get("client_id", "")
                platform_cfg.client_secret = pc.get("client_secret", "")

    return cfg


def load_config(config_file: str | Path | None = None) -> Config:
    global _config

    # Environment variable override
    if config_file is None:
        config_file = os.environ.get("YTCLIP_CONFIG_FILE")

    if config_file:
        path = Path(config_file).expanduser()
        if path.exists():
            with open(path, "rb") as f:
                raw = tomllib.load(f)
            _config = _parse_config(raw)
        else:
            # Config path specified but file not yet created — use defaults
            _config = Config()
    else:
        for candidate in _DEFAULT_CONFIG_PATHS:
            if candidate.exists():
                with open(candidate, "rb") as f:
                    raw = tomllib.load(f)
                _config = _parse_config(raw)
                break
        else:
            _config = Config()

    # Environment variable overrides for output_dir
    if env_out := os.environ.get("YTCLIP_OUTPUT_DIR"):
        _config.general.output_dir = Path(env_out).expanduser()

    _config.general.output_dir.mkdir(parents=True, exist_ok=True)
    return _config


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
