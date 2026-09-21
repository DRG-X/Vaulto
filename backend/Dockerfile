# Vaulto API — FastAPI on Google Cloud Run.
#
# Cloud Run scales to zero, which is why there is no in-process scheduler in this
# service any more. The rate-alert check is an endpoint
# (POST /internal/check-alerts) that Supabase Cron requests every 15 minutes; the
# schedule lives in Postgres, where it survives having no instances running.
#
# Because nothing in here is stateful between requests, Cloud Run may run as many
# instances of this image as it likes.

FROM python:3.11-slim

# Unbuffered so logs reach Cloud Logging as they happen rather than when the
# buffer fills — the difference between watching a deploy and guessing.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg2-binary ships its own libpq, so only the runtime TLS libraries are
# needed here.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first: this layer is cached and only rebuilds when the
# requirements change, not on every code edit.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user. Nothing here writes to the image at runtime.
RUN useradd --create-home --uid 10001 vaulto && chown -R vaulto:vaulto /app
USER vaulto

# Cloud Run injects PORT and expects the container to listen on it. 8080 is its
# default and the value to assume when testing the image locally.
ENV PORT=8080
EXPOSE 8080

# One uvicorn worker. Cloud Run scales by adding INSTANCES, not by asking one
# container to fork; a second worker would just contend for the same CPU
# allocation and double the database connections each instance opens.
#
# --proxy-headers with a trusted wildcard: Cloud Run terminates TLS at its front
# end and passes the real client IP in X-Forwarded-For, which is what the rate
# limiter keys on. Traffic cannot reach the container except through that proxy.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
