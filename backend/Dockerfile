# Vaulto API — FastAPI + APScheduler.
#
# This runs as a LONG-LIVED container, not a serverless function. The alert
# checker is an in-process scheduler that has to be alive between its 15-minute
# ticks, startup migrates the database, and a comparison fans out to 28 provider
# APIs with a 15-second timeout each. None of those survive a function that is
# frozen between requests, which is why the backend does not go on Vercel.

FROM python:3.11-slim

# Unbuffered so logs reach the platform's log viewer as they happen rather than
# when the buffer fills — the difference between watching a deploy and guessing.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg2-binary ships its own libpq, so only the runtime TLS libraries are
# needed here; curl is for the container healthcheck below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first: this layer is cached and only rebuilds when the
# requirements change, not on every code edit.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user. Nothing here writes to the image at runtime.
RUN useradd --create-home --uid 10001 vaulto && chown -R vaulto:vaulto /app
USER vaulto

# $PORT is injected by Render, Railway and Fly; 8000 is the local default.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# One worker on purpose: a second worker would start a SECOND copy of the alert
# scheduler, and both would fire the same alert. Scale with instances behind a
# load balancer only once the scheduler has been moved out of the web process.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
