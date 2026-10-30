FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements-browser.txt .
RUN pip install --no-cache-dir -r requirements-browser.txt && playwright install --with-deps chromium && useradd -m -u 10001 watcher && mkdir -p /app/data && chown watcher:watcher /app/data && chmod -R a+rX /ms-playwright
COPY watcher ./watcher
COPY config.json .
USER watcher
CMD ["python", "-m", "watcher.cli", "run"]
