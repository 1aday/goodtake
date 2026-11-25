FROM node:22-bookworm-slim AS node
FROM python:3.11-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update && apt-get install -y --no-install-recommends \
       ffmpeg chromium tesseract-ocr tesseract-ocr-eng ca-certificates fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
ENV GOODTAKE_HOME=/data GOODTAKE_RUNTIME=/opt/goodtake/runtime CHROME_PATH=/usr/bin/chromium \
    PYTHONUNBUFFERED=1 HF_HUB_DISABLE_TELEMETRY=1
RUN python -m pip install --no-cache-dir '.[local,youtube]' \
    && goodtake --home /tmp/build-setup setup \
    && rm -rf /tmp/build-setup \
    && useradd -m -u 10001 goodtake && mkdir -p /data && chown goodtake:goodtake /data
USER goodtake
VOLUME /data
EXPOSE 3210
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3210/api/status',timeout=3)"
CMD ["goodtake", "studio", "--host", "0.0.0.0", "--no-open"]
