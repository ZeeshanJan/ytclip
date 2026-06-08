# ytclip

> Self-hosted YouTube clip creator. Paste a URL, drag in/out points, download the clip at source quality.

No cloud. No subscription. Runs on your machine.

[![Docker Hub](https://img.shields.io/docker/pulls/zeeshanjan/ytclip?style=flat-square&logo=docker&label=Docker%20Hub)](https://hub.docker.com/r/zeeshanjan/ytclip)
[![GitHub](https://img.shields.io/github/stars/ZeeshanJan/ytclip?style=flat-square&logo=github)](https://github.com/ZeeshanJan/ytclip)
[![MIT License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

---

## Features

### Core
- **Embedded YouTube player** with draggable in/out timeline handles
- **Highest quality by default** — merges best video + audio streams
- **Smart bandwidth** — fetches only the DASH segments covering your clip range; falls back to full download
- **No re-encoding option** — MKV stream-copy preserves the original codec with zero quality loss
- **Audio-only export** — MP3 or AAC
- **Real-time progress** — live ffmpeg output via Server-Sent Events
- **Job queue** — parallel clip jobs, configurable concurrency, persisted in SQLite
- **Clip library** — browse, download, and delete clips from the web UI
- **CLI** — `ytclip clip <url> <start> <end>` for scripting and headless use
- **No Node.js required** — single Python process, no build step
- **Auto-updates yt-dlp** — daily by default, keeps extraction working
- **Optional password auth** — for non-localhost deployments

### Creator Tools
- **Clip Queue / Batch Export** — queue multiple segments, export all at once; each runs as an independent job with live progress
- **Subtitle burn-in** — download and burn English subtitles directly into the video with full style control (font size, color, background, position)
- **Crop** — crop to 9:16 for Reels/Shorts, 1:1 for feed, 4:5 for portrait, or draw a custom region; output resolution shown live
- **Speed control** — 0.25× to 2× with pitch-corrected audio
- **Watermark** — stamp a text handle or upload a logo PNG; four corner positions; the app remembers your last 5 watermarks
- **GIF & WebP export** — palette-optimised animated GIF; WebP for Discord, Notion, and modern embeds
- **Clip presets** — save any form configuration as a named preset, load with one click; stored server-side in SQLite
- **Shareable clip links** — every completed clip gets a public `/share/{id}` page with an embedded player and social share buttons (Twitter/X, WhatsApp, Facebook, Copy Link)
- **Brand Kits** — save named brand profiles (logo, watermark position, subtitle style, default format); apply all settings at once from the editor
- **Direct platform publishing** — publish clips to YouTube Shorts, Instagram Reels, TikTok, and LinkedIn without downloading and re-uploading

---

## Quick Start

### Docker (recommended)

The pre-built image is on Docker Hub — no clone needed.

**One-liner:**

```bash
docker run -d -p 8000:8000 -v ./clips:/clips --restart unless-stopped zeeshanjan/ytclip:latest
```

**docker-compose (recommended for persistent config):**

```bash
curl -O https://raw.githubusercontent.com/ZeeshanJan/ytclip/main/docker-compose.yml
docker compose up -d
```

Or clone the repo if you want to customise the compose file:

```bash
git clone https://github.com/ZeeshanJan/ytclip.git
cd ytclip
docker compose up -d
```

Open [http://localhost:8000](http://localhost:8000). Clips are saved to `./clips/`.

> **Docker Hub:** [hub.docker.com/r/zeeshanjan/ytclip](https://hub.docker.com/r/zeeshanjan/ytclip)

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
# Public base URL — required for OAuth redirect URIs when using platform publishing
public_url = "http://localhost:8000"

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

# ── Platform Publishing (optional) ───────────────────────────────────────────
# Add credentials for each platform you want to publish to.
# Connect accounts in the app at Settings → Platform Connections.

[platforms.youtube]
client_id = ""
client_secret = ""

[platforms.instagram]
client_id = ""
client_secret = ""

[platforms.tiktok]
client_id = ""
client_secret = ""

[platforms.linkedin]
client_id = ""
client_secret = ""
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

## Platform Publishing

Publish clips directly to YouTube Shorts, Instagram Reels, TikTok, and LinkedIn — no downloading and re-uploading.

### Setup overview

1. Set `public_url` to your ytclip instance's public address in `config.toml`
2. Create a developer app on each platform (see below) and add the credentials
3. Restart ytclip, open **Settings → Platform Connections**, and click **Connect** for each platform
4. After a clip completes, click the platform icon buttons on the job card to publish

### YouTube Shorts

1. Open [Google Cloud Console](https://console.cloud.google.com/) → create a project
2. Enable **YouTube Data API v3** (APIs & Services → Library)
3. Create **OAuth 2.0 credentials** (APIs & Services → Credentials → OAuth client ID → Web application)
4. Add `{public_url}/publish/callback/youtube` as an Authorized redirect URI
5. Copy **Client ID** and **Client secret** to `[platforms.youtube]` in config.toml

### Instagram Reels

1. Open [Meta for Developers](https://developers.facebook.com/) → Create App → Business type
2. Add the **Instagram Graph API** product
3. Under App Settings → Basic, add `{public_url}/publish/callback/instagram` to Valid OAuth Redirect URIs
4. Requires an **Instagram Business or Creator account** linked to a Facebook Page
5. Copy **App ID** → `client_id` and **App Secret** → `client_secret`

### TikTok

1. Register at [TikTok for Developers](https://developers.tiktok.com/) → My Apps → Create app
2. Request scopes: `user.info.basic`, `video.publish`, `video.upload`
3. Add `{public_url}/publish/callback/tiktok` as a redirect URI
4. Copy **Client Key** → `client_id` and **Client Secret** → `client_secret`

### LinkedIn

1. Open [LinkedIn Developer Portal](https://developer.linkedin.com/) → Create App
2. Enable the **Share on LinkedIn** product
3. Under Auth → Authorized redirect URLs, add `{public_url}/publish/callback/linkedin`
4. Copy **Client ID** and **Client Secret**

> **Note:** TikTok does not return a direct post URL after publishing — the button links to your TikTok profile instead.

---

## Brand Kits

Brand kits save a complete set of branding settings — logo, watermark position, subtitle style, and default format — under a single name. Apply a kit in the editor with one click.

**Create a kit:** Settings → Brand Kits → New Brand Kit

**Apply a kit:** In the clip editor, use the **Brand Kit** dropdown at the top of the controls panel. All settings update instantly — watermark, subtitle style, and output format.

Kits are stored in SQLite alongside presets. The logo file is stored in `~/.ytclip/brand_logos/`.

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
