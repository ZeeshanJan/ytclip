# ytclip

> Self-hosted YouTube clip creator. Paste a URL, drag in/out points, download the clip at source quality.

No cloud. No subscription. Runs on your machine.

---

## Features

- **Embedded YouTube player** with draggable in/out timeline handles
- **Highest quality by default** — merges best video + audio streams
- **Smart bandwidth** — fetches only the DASH segments covering your clip range; falls back to full download
- **No re-encoding option** — MKV stream-copy preserves the original codec with zero quality loss
- **Audio-only export** — MP3 or AAC
- **Optional subtitles** — include or burn in a subtitle track
- **Real-time progress** — live ffmpeg progress via Server-Sent Events
- **Job queue** — parallel clip jobs, configurable concurrency, persisted across restarts
- **Clip library** — browse, download, and delete your clips from the web UI
- **CLI** — `ytclip clip <url> <start> <end>` for scripting and headless use
- **No Node.js required** — single Python process, no build step
- **Auto-updates yt-dlp** — daily by default, keeps extraction working
- **Optional password auth** — for non-localhost deployments

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/ZeeshanJan/ytclip.git
cd ytclip
docker compose up -d
```

Open [http://localhost:8000](http://localhost:8000). Clips are saved to `./clips/`.

### Bare Python (Python 3.12+ required)

Requires [ffmpeg](https://ffmpeg.org/download.html) on your `PATH` (or omit it — a static build is bundled as fallback).

```bash
pip install ytclip
ytclip serve
```

Or from source:

```bash
git clone https://github.com/ZeeshanJan/ytclip.git
cd ytclip
pip install .
ytclip serve
```

Open [http://localhost:8000](http://localhost:8000).

---

## Configuration

```bash
cp config.example.toml config.toml
```

ytclip looks for a config file in this order:

1. `YTCLIP_CONFIG_FILE` environment variable
2. `/config/config.toml` (Docker volume path)
3. `~/.ytclip/config.toml`
4. `./config.toml` (current directory)

Key options:

```toml
[general]
output_dir = "~/yt-clips"          # where clips are saved
max_concurrent_jobs = 2            # parallel download jobs
max_clip_duration = 0              # 0 = no limit (seconds)

[quality]
max_quality = "best"               # "best" | "2160p" | "1080p" | "720p" | "480p"
prefer_segments_only = false       # true = never download full stream (faster, may fail on some videos)

[output]
filename_template = "{title}_{start}-{end}_{id}"
default_format = "mp4"             # "mp4" | "mkv" | "mp3" | "aac"
include_subtitles = false

[auth]
enabled = false
password = ""                      # set a password when enabled = true

[ytdlp]
auto_update = true
auto_update_interval_hours = 24
cookies_file = ""                  # path to Netscape cookies file (see Age-Restricted Videos)
```

See [`config.example.toml`](config.example.toml) for the full reference with comments.

---

## Output Formats

| Format | Codec        | Notes                                                      |
| ------ | ------------ | ---------------------------------------------------------- |
| `mp4`  | H.264 + AAC  | Universal compatibility; VP9/AV1 sources are re-encoded    |
| `mkv`  | Source codec | Stream-copy — zero re-encoding, preserves original quality |
| `mp3`  | MP3          | Audio only                                                 |
| `aac`  | AAC          | Audio only; stream-copied from AAC source                  |

---

## CLI Usage

```bash
# Start the web server
ytclip serve
ytclip serve --host 0.0.0.0 --port 8080

# Create a clip directly (no server needed)
ytclip clip "https://youtube.com/watch?v=..." --end 1:30
ytclip clip "https://youtube.com/watch?v=..." --start 0:30 --end 2:00 --format mkv
ytclip clip "https://youtube.com/watch?v=..." --start 60 --end 90 --format mp3

# Delegate to a running server instead of running locally
ytclip clip "https://..." --start 0:30 --end 1:00 --server-url http://localhost:8000

# List saved clips
ytclip library

# Show versions
ytclip version
```

---

## Age-Restricted Videos

Export your YouTube cookies from your browser (the account that has access):

```bash
# Using a browser extension like "Get cookies.txt LOCALLY" → save as youtube-cookies.txt
# Or via yt-dlp directly:
yt-dlp --cookies-from-browser chrome --cookies youtube-cookies.txt --skip-download "https://youtube.com"
```

Then point ytclip to the file:

```toml
[ytdlp]
cookies_file = "/path/to/youtube-cookies.txt"
```

---

## Self-Hosting Beyond Localhost

Enable password auth before exposing ytclip to a network:

```toml
[auth]
enabled = true
password = "your-strong-password"
```

Running behind a reverse proxy is recommended for HTTPS. Example **Caddy** config:

```
ytclip.yourdomain.com {
    reverse_proxy localhost:8000
}
```

Example **nginx** config:

```nginx
server {
    listen 443 ssl;
    server_name ytclip.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # Required for SSE progress streaming
        proxy_buffering off;
        proxy_cache off;
    }
}
```

---

## Development

```bash
git clone https://github.com/ZeeshanJan/ytclip.git
cd ytclip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Unit tests (no network required)
pytest

# Integration tests (downloads a real video — requires network + ffmpeg)
pytest -m integration

# Dev server with auto-reload
uvicorn ytclip.web.app:create_app --factory --host 127.0.0.1 --port 8765 --reload
```

**Stack:** Python 3.12 · FastAPI · Jinja2 + HTMX · SQLite (aiosqlite) · yt-dlp · ffmpeg · DaisyUI

---

## Tech Stack

| Layer         | Choice                            | Reason                                        |
| ------------- | --------------------------------- | --------------------------------------------- |
| Language      | Python 3.12+                      | yt-dlp native, ffmpeg ecosystem               |
| Web framework | FastAPI                           | Async, handles concurrent clip jobs           |
| UI            | Jinja2 + HTMX                     | No Node.js, no build step                     |
| Progress      | Server-Sent Events                | One-way push from ffmpeg → browser            |
| Config        | TOML                              | Clean syntax, stdlib `tomllib` in 3.12        |
| Database      | SQLite                            | Zero-config, single-user appropriate          |
| yt-dlp        | Python library                    | Programmatic format selection, progress hooks |
| ffmpeg        | System + `static-ffmpeg` fallback | No manual install friction                    |

---

## Contributing

Issues and pull requests are welcome.

- **Bug reports** — open an issue with steps to reproduce and the output of `ytclip version`
- **Feature requests** — open an issue describing the use case before implementing
- **Pull requests** — keep them focused; one feature or fix per PR; include tests where applicable

---

## Support

If ytclip saves you time and you'd like to support ongoing maintenance, you can:

- ⭐ **Star this repository** — it helps others find the project
- 🐛 **Report bugs and suggest improvements** — open an issue
- 📣 **Share the project** — tell others who might find it useful
- ☕ **Buy me a coffee** — [buymeacoffee.com/zeeshan](https://buymeacoffee.com/zeeshan)

Support is completely optional. ytclip will always be free and open source.

---

## Legal Disclaimer

This tool is for **personal use only**. You are solely responsible for ensuring that any content you download or clip complies with YouTube's [Terms of Service](https://www.youtube.com/t/terms), applicable copyright law, and the rights of content owners.

ytclip does not host, store, or redistribute any video content. All clips are saved only to your own machine. The authors accept no liability for how you use this tool.

---

## License

[MIT](LICENSE)
