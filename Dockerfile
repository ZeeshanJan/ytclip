FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy everything first so the package is present during install
COPY . .
RUN pip install --no-cache-dir .

RUN mkdir -p /clips /config

VOLUME ["/clips", "/config"]

ENV YTCLIP_OUTPUT_DIR=/clips

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

CMD ["ytclip", "serve", "--host", "0.0.0.0", "--port", "8000"]
