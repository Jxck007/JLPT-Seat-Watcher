FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY pyproject.toml README.md LICENSE requirements.txt ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 watcher \
    && mkdir -p /app/data /app/logs /ms-playwright \
    && chown -R watcher:watcher /app /ms-playwright

COPY --chown=watcher:watcher main.py monitor.py notify_test.py status.py ./

USER watcher

VOLUME ["/app/data", "/app/logs"]

HEALTHCHECK --interval=5m --timeout=15s --start-period=1m --retries=2 \
  CMD ["python", "-m", "jlpt_seat_watcher", "health"]

CMD ["python", "main.py"]
